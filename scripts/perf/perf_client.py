
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Optional

import httpx
import pyotp


@dataclass
class ProcessSample:

    cpu_percent: float
    rss_kb: int
    child_count: int


def sample_process(pid: int) -> Optional[ProcessSample]:
    proc = subprocess.run(
        ["ps", "-o", "%cpu=,rss=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    parts = proc.stdout.split()
    cpu = float(parts[0])
    rss_kb = int(parts[1])
    children = subprocess.run(
        ["pgrep", "-P", str(pid)], capture_output=True, text=True, check=False
    )
    child_count = len([ln for ln in children.stdout.splitlines() if ln.strip()])
    return ProcessSample(cpu_percent=cpu, rss_kb=rss_kb, child_count=child_count)


def count_descendants(pid: int) -> int:
    direct = subprocess.run(
        ["pgrep", "-P", str(pid)], capture_output=True, text=True, check=False
    )
    kids = [ln for ln in direct.stdout.splitlines() if ln.strip()]
    total = len(kids)
    for kid in kids:
        total += count_descendants(int(kid))
    return total


class PerfClient:

    def __init__(self, base_url: str, totp_secret: str) -> None:
        self.base_url = base_url
        self._totp_secret = totp_secret
        self._http = httpx.Client(base_url=base_url, timeout=20.0)
        self.token: Optional[str] = None

    def login(self) -> str:
        code = pyotp.TOTP(self._totp_secret).now()
        resp = self._http.post("/api/v1/auth/verify", json={"code": code})
        if resp.status_code != 200:
            raise RuntimeError(f"perf login refused: {resp.status_code} {resp.text[:300]}")
        self.token = resp.json()["access_token"]
        self._http.headers["Authorization"] = f"Bearer {self.token}"
        return self.token

    def create_session(self, working_dir: str, label: str) -> dict:
        resp = self._http.post(
            "/api/v1/sessions",
            json={
                "working_dir": working_dir,
                "auto_start_claude": True,
                "agent_type": "shell",
                "label": label,
            },
        )
        if resp.status_code != 201:
            raise RuntimeError(f"create refused: {resp.status_code} {resp.text[:300]}")
        return resp.json()

    def mark_account_welcome_seen(self) -> None:
        prefs = self._http.get("/api/v1/preferences")
        prefs.raise_for_status()
        revision = prefs.json()["revision"]
        saved = self._http.patch(
            "/api/v1/preferences",
            json={
                "changes": {"account_welcome_seen": True},
                "expected_revision": revision,
            },
        )
        saved.raise_for_status()
        if saved.json()["values"].get("account_welcome_seen") is not True:
            raise RuntimeError("account welcome preference was not saved")

    def list_sessions(self) -> list[dict]:
        resp = self._http.get("/api/v1/sessions/list")
        resp.raise_for_status()
        return resp.json()

    def row_for(self, session_id: str) -> Optional[dict]:
        for row in self.list_sessions():
            if (row.get("session") or {}).get("id") == session_id:
                return row
        return None

    def create_toast(self, session_id: str, kind: str, title: str, body: str) -> dict:
        resp = self._http.post(
            f"/api/v1/sessions/{session_id}/toasts",
            json={"kind": kind, "title": title, "body": body},
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"toast refused: {resp.status_code} {resp.text[:300]}")
        return resp.json()

    def close(self) -> None:
        self._http.close()


def wait_until(predicate: Callable[[], object], timeout: float, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())
