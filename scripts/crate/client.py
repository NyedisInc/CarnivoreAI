
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Tuple
from urllib.parse import quote, urlencode

from scripts.crate.errors import ApiError, AuthError, CrateScriptError, IntegrityError, JobFailedError, JobTimeoutError
from scripts.crate.tokens import TokenSource
from scripts.crate.transport import CHUNK, HttpTransport, Response, Transport

PLUGIN_ID = "crate"
BASE = f"/api/v1/cplugs/{PLUGIN_ID}"
HOST_PATH = BASE
POLL_INTERVAL_S = 1.0
JOB_TIMEOUT_S = 6 * 3600.0
_STATES_RUNNING = ("running",)
_FILENAME = re.compile(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', re.IGNORECASE)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


class CrateClient:

    def __init__(self, base_url: str = "", tokens: Optional[TokenSource] = None, *, transport: Optional[Transport] = None,
                 poll_interval: float = POLL_INTERVAL_S, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.tokens = tokens
        self.transport: Transport = transport or HttpTransport(base_url)
        self.poll_interval, self._sleep, self._clock = poll_interval, sleep, clock

    def __repr__(self) -> str:
        return f"CrateClient({type(self.transport).__name__}, tokens={self.tokens!r})"

    def _headers(self, extra: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
        headers: Dict[str, str] = {"Accept": "application/json"}
        if self.tokens is not None:
            headers["Authorization"] = "Bearer " + self.tokens.token()
        headers.update(extra or {})
        return headers

    def _fail(self, response: Response) -> CrateScriptError:
        raw = response.read()
        code: Optional[str] = None
        detail: Any = None
        message = f"HTTP {response.status}"
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            data = {}
        body = data.get("detail") if isinstance(data, dict) else None
        if isinstance(body, dict):
            code, detail = body.get("code"), body
            message = f"{code or message}: {body.get('detail') or ''}".strip()
        elif isinstance(body, str):
            message = f"HTTP {response.status}: {body}"
        if response.status == 401 or (response.status == 403 and code is None):
            return AuthError(f"the host refused the token ({message})", code=code, detail=detail)
        return ApiError(message, status=response.status, code=code, detail=detail)

    def request(self, method: str, path: str, body: Optional[Mapping[str, Any]] = None) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        extra = {"Content-Type": "application/json"} if data is not None else None
        response = self.transport.send(method, path, self._headers(extra), data)
        if response.status >= 400:
            raise self._fail(response)
        raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else {}


    def plugin_row(self) -> Dict[str, Any]:
        return self.request("GET", HOST_PATH)

    def setup(self) -> Dict[str, Any]:
        row = self.plugin_row()
        wanted = list(row["permissions"]["app"])
        changed = not row["enabled"] or sorted(row["grants"]["app"]) != sorted(wanted)
        if changed:
            row = self.request("PUT", HOST_PATH, {"revision": row["revision"], "enabled": True, "grants": {"app": wanted}})
        listing = self.folder_crates("primary")
        return {"enabled": row["enabled"], "grants": row["grants"]["app"], "changed": changed, "state": row["state"],
                "folder_ok": True, "crates": len(listing.get("crates", []))}


    def plan_export(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        return self.request("POST", BASE + "/plan", body)

    def start_export(self, body: Mapping[str, Any], fingerprint: str) -> Dict[str, Any]:
        return self.request("POST", BASE + "/exports", {**body, "fingerprint": fingerprint})

    def job(self, job_id: str) -> Dict[str, Any]:
        return self.request("GET", f"{BASE}/jobs/{quote(job_id, safe='')}")

    def wait_job(self, job_id: str, timeout: float = JOB_TIMEOUT_S) -> Dict[str, Any]:
        deadline = self._clock() + timeout
        while True:
            view = self.job(job_id)
            if view["state"] not in _STATES_RUNNING:
                break
            if self._clock() >= deadline:
                raise JobTimeoutError(f"job {job_id} was still {view.get('phase') or 'running'} after {timeout:.0f}s", detail=view)
            self._sleep(self.poll_interval)
        if view["state"] != "done":
            err = view.get("error") or {}
            raise JobFailedError(f"job {job_id} {view['state']}: {err.get('code', '')} {err.get('detail', '')}".strip(),
                                 code=err.get("code"), detail=view)
        return view

    def export(self, body: Mapping[str, Any], timeout: float = JOB_TIMEOUT_S) -> Dict[str, Any]:
        plan = self.plan_export(body)
        if not plan.get("ok"):
            raise ApiError("the export plan is blocked: " + ", ".join(str(b.get("code")) for b in plan.get("blockers", [])),
                           status=200, code="plan_blocked", detail=plan.get("blockers"))
        started = self.start_export(body, plan["fingerprint"])
        return self.wait_job(started["job_id"], timeout)["result"]


    def folder_crates(self, folder: str = "primary") -> Dict[str, Any]:
        return self.request("GET", f"{BASE}/folders/{quote(folder, safe='')}/crates")

    def _download_part(self, bundle_id: str, part: str) -> Response:
        query = urlencode({"part": part})
        response = self.transport.send("GET", f"{BASE}/bundles/{quote(bundle_id, safe='')}/download?{query}", self._headers())
        if response.status >= 400:
            raise self._fail(response)
        return response

    def download_bundle(self, bundle_id: str, dest_dir: Path, expected_sha256: Optional[str] = None) -> Tuple[Path, str]:
        dest_dir.mkdir(parents=True, exist_ok=True)
        response = self._download_part(bundle_id, "crate")
        match = _FILENAME.search(response.headers.get("content-disposition", ""))
        name = Path(match.group(1)).name if match else f"{bundle_id}.crate"
        final, temp = dest_dir / name, dest_dir / f".{name}.partial"
        digest = hashlib.sha256()
        try:
            with open(temp, "xb") as out:
                for block in response.chunks:
                    digest.update(block)
                    out.write(block)
            response.close()
            got = digest.hexdigest()
            side = self._download_part(bundle_id, "sha256").read().decode("utf-8", "replace").split()
            host_sha = side[0].lower() if side else ""
            if got != host_sha or (expected_sha256 and got != expected_sha256.lower()):
                raise IntegrityError(f"downloaded {name} hashes to {got[:12]}..., host says {(expected_sha256 or host_sha)[:12]}...",
                                     code="sha256_mismatch")
            if final.exists():
                raise FileExistsError(str(final))
            os.replace(temp, final)
        finally:
            response.close()
            if temp.exists():
                temp.unlink()
        return final, got

    def upload_crate(self, path: Path, sha256: Optional[str] = None) -> Dict[str, Any]:
        sha = (sha256 or sha256_of(path)).lower()
        size = path.stat().st_size
        headers = self._headers({"X-Crate-Name": path.name, "X-Crate-Sha256": sha, "Content-Type": "application/octet-stream"})
        with open(path, "rb") as handle:
            response = self.transport.send("POST", BASE + "/folders/primary/crates/upload", headers, handle, size)
            if response.status >= 400:
                raise self._fail(response)
            answer = json.loads(response.read().decode("utf-8"))
        if answer.get("sha256") != sha or answer.get("size") != size:
            raise IntegrityError(f"the host stored {answer.get('name')} as {answer.get('size')} bytes / {str(answer.get('sha256'))[:12]}...",
                                 code="upload_mismatch", detail=answer)
        return answer


    def plan_import(self, body: Mapping[str, Any]) -> Dict[str, Any]:
        return self.request("POST", BASE + "/imports/plan", body)

    def start_import(self, body: Mapping[str, Any], fingerprint: str) -> Dict[str, Any]:
        return self.request("POST", BASE + "/imports", {**body, "fingerprint": fingerprint})

    def imports(self) -> Dict[str, Any]:
        return self.request("GET", BASE + "/imports")

    def receipt(self, import_id: str) -> Dict[str, Any]:
        return self.request("GET", f"{BASE}/imports/{quote(import_id, safe='')}")

    def undo_preview(self, import_id: str) -> Dict[str, Any]:
        return self.request("GET", f"{BASE}/imports/{quote(import_id, safe='')}/undo")

    def undo(self, import_id: str) -> Dict[str, Any]:
        return self.request("POST", f"{BASE}/imports/{quote(import_id, safe='')}/undo", {})
