#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

_WORKDIR = tempfile.mkdtemp(prefix="cc_verify_wd_")
_LOGDIR = tempfile.mkdtemp(prefix="cc_verify_logs_")
_STATEDIR = tempfile.mkdtemp(prefix="cc_verify_state_")
os.environ["DEFAULT_WORKING_DIR"] = _WORKDIR
os.environ["LOG_DIRECTORY"] = _LOGDIR
os.environ["CLOUDE_STATE_DIR"] = _STATEDIR
os.environ.setdefault("TOTP_SECRET", "verifysecretnotreal")
os.environ.setdefault("JWT_SECRET", "verifyjwtnotreal")

# ruff: noqa: E402
import httpx

from src.api.auth import require_auth
from src.main import app

SOCKET = "cloudeverify"
EXTERNAL_NAME = "verifyext"
CREATED_PROJECT = "verifyown"

app.dependency_overrides[require_auth] = lambda: True

from src.core import tmux_backend as _tmux_backend  # noqa: E402

_ORIGINAL_TMUX_INIT = _tmux_backend.TmuxBackend.__init__


def _pinned_socket_init(self, *args, **kwargs) -> None:
    _ORIGINAL_TMUX_INIT(self, *args, **kwargs)
    self.socket_name = SOCKET


_tmux_backend.TmuxBackend.__init__ = _pinned_socket_init

_failures: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    if actual == expected:
        print(f"ok   - {label} (= {actual!r})")
    else:
        _failures.append(label)
        print(f"FAIL - {label}: expected {expected!r}, got {actual!r}")


def tmux(*args: str, check_rc: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-L", SOCKET, *args],
        capture_output=True,
        text=True,
        check=check_rc,
    )


async def badges(client: httpx.AsyncClient) -> dict[str, bool]:
    out: dict[str, bool] = {}
    resp = await client.get("/sessions/attachable")
    resp.raise_for_status()
    for row in resp.json():
        out[row["name"]] = row["created_by_cloude"]
    resp = await client.get("/sessions/list")
    resp.raise_for_status()
    for info in resp.json():
        name = info.get("tmux_session")
        if name:
            out[name] = info["created_by_cloude"]
    return out


async def ids(client: httpx.AsyncClient) -> dict[str, str]:
    resp = await client.get("/sessions/list")
    resp.raise_for_status()
    return {
        i["tmux_session"]: i["session"]["id"]
        for i in resp.json()
        if i.get("tmux_session")
    }


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://verify.local/api/v1",
    )


async def phase_one() -> tuple[str, dict[str, bool]]:
    async with app.router.lifespan_context(app):
        async with make_client() as client:
            resp = await client.post(
                "/sessions",
                json={
                    "working_dir": _WORKDIR,
                    "auto_start_claude": False,
                    "project_name": CREATED_PROJECT,
                },
            )
            resp.raise_for_status()
            created_name = resp.json()["tmux_session"]
            print(f"created via POST /sessions: {created_name}")

            tmux("new-session", "-d", "-s", EXTERNAL_NAME)
            print(f"created directly in tmux: {EXTERNAL_NAME}")

            b = await badges(client)
            check("created session badges owned (before adopt)",
                  b.get(created_name), True)
            check("external session badges external (before adopt)",
                  b.get(EXTERNAL_NAME), False)

            resp = await client.post(
                "/sessions/adopt",
                json={"session_name": EXTERNAL_NAME, "confirm_detach": False},
            )
            resp.raise_for_status()

            b = await badges(client)
            check("created session still owned (external now OPEN)",
                  b.get(created_name), True)
            check("adopted session badges OURS once ADOPTED",
                  b.get(EXTERNAL_NAME), True)

            live_ids = await ids(client)
            print(f"ids while open: {live_ids}")

            for sid in live_ids.values():
                await client.post("/sessions/detach", params={"session_id": sid})
            b = await badges(client)
            check("created session still owned once CLOSED",
                  b.get(created_name), True)
            check("adopted session still OURS once CLOSED",
                  b.get(EXTERNAL_NAME), True)

            for name in (created_name, EXTERNAL_NAME):
                resp = await client.post(
                    "/sessions/adopt",
                    json={"session_name": name, "confirm_detach": False},
                )
                resp.raise_for_status()
            b = await badges(client)
            check("created session still owned once RE-OPENED",
                  b.get(created_name), True)
            check("adopted session still OURS once RE-OPENED",
                  b.get(EXTERNAL_NAME), True)

            return created_name, b


async def phase_two(created_name: str, before: dict[str, bool]) -> None:
    async with app.router.lifespan_context(app):
        async with make_client() as client:
            for name in (created_name, EXTERNAL_NAME):
                try:
                    await client.post(
                        "/sessions/adopt",
                        json={"session_name": name, "confirm_detach": False},
                    )
                except Exception:
                    pass

            live_ids = await ids(client)
            print(f"ids after restart: {live_ids}")
            check("restart re-minted an adopted: id for the OWNED session",
                  str(live_ids.get(created_name, "")).startswith("adopted:"),
                  True)

            after = await badges(client)
            check("created session STILL owned after restart",
                  after.get(created_name), before.get(created_name))
            check("adopted session STILL ours after restart",
                  after.get(EXTERNAL_NAME), before.get(EXTERNAL_NAME))
            check("owned badge value after restart", after.get(created_name), True)
            check("adopted badge value after restart",
                  after.get(EXTERNAL_NAME), True)


async def main() -> int:
    try:
        created_name, before = await phase_one()
        await phase_two(created_name, before)
    finally:
        tmux("kill-server")
        print(f"killed tmux socket {SOCKET}")

    print(f"\n{len(_failures)} failed")
    if _failures:
        for f in _failures:
            print(f"  FAILED: {f}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
