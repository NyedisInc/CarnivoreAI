
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from src.core.federation import peer_links
from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.pack.jobs.types import (AdmitBody, CollectAnswer, HostState, JobError, JobIdBody, ReplyBody, RunStatus,
                                      StartBody, StatusAnswer, StopBody)
from src.core.pack.jobs import bundle_io
from src.core.pack.transport import blobs

SSH_PREFIX = "ssh:"
JOBS_PATH = "/federation/pack/jobs"
ADMIT_TIMEOUT_S = 5.0


class Target(Protocol):

    install_id: str
    label: str

    async def admit(self, body: AdmitBody) -> None:
        pass

    async def start(self, body: StartBody) -> str:
        pass

    async def status(self, job_id: str) -> RunStatus:
        pass

    async def status_full(self, job_id: str) -> StatusAnswer:
        pass

    async def reply(self, body: ReplyBody) -> None:
        pass

    async def collect(self, job_id: str) -> CollectAnswer:
        pass

    async def fetch_result(self, job_id: str, answer: CollectAnswer, state_dir: Path) -> str:
        pass

    async def stop(self, job_id: str, keep_files: bool) -> None:
        pass

    async def release(self, job_id: str) -> None:
        pass

    async def send_bundle(self, path: str) -> str:
        pass

    async def install(self, job_id: str, project_uid: str, tools: List[str]) -> List[Dict[str, Any]]:
        pass

    async def install_status(self, install_id: str) -> Dict[str, Any]:
        pass


def _refusal(status: int, body: Any) -> JobError:
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        return JobError(str(detail.get("code") or f"http_{status}"), str(detail.get("detail") or detail.get("rule") or ""), status)
    return JobError(f"http_{status}", str(detail or "")[:300], status)


class PeerTarget:

    def __init__(self, install_id: str, label: str, request: blobs.Request, slow: Optional[blobs.Request] = None) -> None:
        self.install_id, self.label = install_id, label
        self._request, self._slow = request, slow or request

    async def _post(self, verb: str, body: Dict[str, Any], *, slow: bool = False, timeout: Optional[float] = None) -> Any:
        call = (self._slow if slow else self._request)("POST", f"{JOBS_PATH}/{verb}", json=body)
        try:
            status, answer = await (asyncio.wait_for(call, timeout) if timeout else call)
        except (PeerUnreachable, PeerRefused, asyncio.TimeoutError, OSError) as exc:
            raise JobError("unreachable", f"{self.label} did not answer ({type(exc).__name__})", 502) from exc
        if status != 200:
            raise _refusal(status, answer)
        return answer

    async def admit(self, body: AdmitBody) -> None:
        await self._post("admit", body.model_dump(), timeout=ADMIT_TIMEOUT_S)

    async def start(self, body: StartBody) -> str:
        answer = await self._post("start", body.model_dump())
        return str((answer or {}).get("state", "preparing"))

    async def status_full(self, job_id: str) -> StatusAnswer:
        return StatusAnswer(**(await self._post("status", JobIdBody(job_id=job_id).model_dump()) or {}))

    async def status(self, job_id: str) -> RunStatus:
        got = await self.status_full(job_id)
        return RunStatus(HostState(got.state), got.exit_code, got.detail, got.output_tail, got.output_bytes)

    async def reply(self, body: ReplyBody) -> None:
        await self._post("reply", body.model_dump())

    async def collect(self, job_id: str) -> CollectAnswer:
        return CollectAnswer(**(await self._post("collect", JobIdBody(job_id=job_id).model_dump(), slow=True) or {}))

    async def fetch_result(self, job_id: str, answer: CollectAnswer, state_dir: Path) -> str:
        try:
            return str(bundle_io.received_path(state_dir, answer.blob_id or "", sender=self.install_id))
        except blobs.BlobError as exc:
            raise JobError(exc.code, "the result did not arrive", exc.status) from exc

    async def stop(self, job_id: str, keep_files: bool) -> None:
        await self._post("stop", StopBody(job_id=job_id, keep_files=keep_files).model_dump())

    async def release(self, job_id: str) -> None:
        await self._post("release", JobIdBody(job_id=job_id).model_dump())

    async def install(self, job_id: str, project_uid: str, tools: List[str]) -> List[Dict[str, Any]]:
        answer = await self._post("install", {"job_id": job_id, "project_uid": project_uid, "tools": tools})
        return list((answer or {}).get("installs") or [])

    async def install_status(self, install_id: str) -> Dict[str, Any]:
        call = self._request("GET", f"{JOBS_PATH}/install/{install_id}")
        try:
            status, answer = await asyncio.wait_for(call, ADMIT_TIMEOUT_S * 2)
        except (PeerUnreachable, PeerRefused, asyncio.TimeoutError, OSError) as exc:
            raise JobError("unreachable", f"{self.label} did not answer ({type(exc).__name__})", 502) from exc
        if status != 200:
            raise _refusal(status, answer)
        return dict(answer or {})

    async def send_bundle(self, path: str) -> str:
        try:
            return await blobs.send_file(self._slow, str(Path(path)), blob_id=blobs.new_id(), kind="bundle")
        except blobs.BlobError as exc:
            raise JobError(exc.code, "the bundle upload was refused", exc.status) from exc
        except (PeerUnreachable, PeerRefused, asyncio.TimeoutError, OSError) as exc:
            raise JobError("unreachable", f"{self.label} did not answer ({type(exc).__name__})", 502) from exc


def peer_target(install_id: str) -> PeerTarget:
    links = peer_links.LINKS
    client = links.client(install_id) if links is not None else None
    if client is None:
        raise JobError("unreachable", "that computer is not connected", 502)
    return PeerTarget(install_id, install_id, blobs.request_via(client, 20.0), blobs.request_via(client, 300.0))


def is_ssh(install_id: str) -> bool:
    return install_id.startswith(SSH_PREFIX)


def target_for(install_id: str) -> Target:
    if is_ssh(install_id):
        from src.core.pack.jobs.ssh import target as ssh_target

        return ssh_target.ssh_target_for(install_id[len(SSH_PREFIX):])
    return peer_target(install_id)
