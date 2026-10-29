
from __future__ import annotations

import asyncio
import contextlib
import os
import pty
import select
import signal
import shutil
import struct
import subprocess
import termios
import time
import fcntl
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from textual.app import App
from textual.widgets import OptionList

from src.core.tmux_discovery import tmux_argv_prefix
from src.tui import attach
from tests.socket_guard import TEST_SOCKET_NAME
from src.tui.app import MainScreen
from src.tui.listing_store import ListingStore
from src.tui.screens.sessions import SessionsTable


def wrap(name: str, status: str, **extra: Any) -> dict[str, Any]:
    return {"session": {"id": name, "name": name, "working_dir": f"/w/{name}"}, "session_uuid": f"u-{name}",
            "label": name, "tmux_session": f"carnivore_{name}", "activity_status": status, **extra}


ROWS = [wrap("live", "idle"), wrap("gone", "dead"), wrap("far", "idle", host_key="peer-x", host_label="hosta")]
PROFILES = [{"id": "p1", "label": "plain", "harness": "claude"}, {"id": "p2", "label": "fast", "harness": "codex", "default": True}]


class Harness(App[None]):

    def __init__(self) -> None:
        super().__init__()
        snap = {"stream": "s", "seq": 1, "collections": {"list": {"rows": ROWS, "ok": True}}}

        async def fetch() -> dict[str, Any]:
            return snap

        self.events = SimpleNamespace(listing=ListingStore(fetch), down=False, on_topics=lambda fn: (lambda: None),
                                      topic_pushed=lambda topic: False)
        self.calls: list[tuple[str, str, Any]] = []

        async def request(method: str, path: str, **kw: Any) -> httpx.Response:
            self.calls.append((method, path, kw.get("json")))
            if path == "/api/v1/preferences":
                return httpx.Response(200, json={"values": {}})
            if path == "/api/v1/approvals":
                return httpx.Response(200, json={"items": []})
            if path == "/api/v1/launch-profiles":
                return httpx.Response(200, json={"profiles": PROFILES})
            if path.endswith("/sleep"):
                return httpx.Response(200, json={"status": "asleep"})
            if path == "/api/v1/sessions/respawn":
                return httpx.Response(200, json={"ok": True, "detail": "restarted"})
            if method == "GET":
                return httpx.Response(200, json={})
            return httpx.Response(200, json={"success": True}) if method == "PATCH" else httpx.Response(201, json={})

        self.client = SimpleNamespace(request=request)

    async def on_mount(self) -> None:
        await self.events.listing.resync()
        await self.push_screen(MainScreen())

    def acted(self) -> list[tuple[str, str, Any]]:
        return [c for c in self.calls if c[0] != "GET"]


def test_actions_pilot(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[Any] = []
    monkeypatch.setattr(attach, "run", lambda plan: ran.append(plan) or 0)
    monkeypatch.setattr(attach, "socket_name", lambda: "cloude")
    monkeypatch.setattr(attach, "read_pane_size", lambda prefix, name: None)
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setattr(App, "suspend", lambda self: contextlib.nullcontext())

    async def run() -> None:
        app = Harness()
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            table = app.screen.query_one(SessionsTable)
            assert table.row_count == 3

            await pilot.press("enter")
            assert ran[0].argvs[0][-1] == "=carnivore_live" and ran[0].suspend

            await pilot.press("u")
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()
            assert app.acted() == [("PATCH", "/api/v1/sessions/carnivore_live/unread", {"unread": False}),
                                   ("POST", "/api/v1/sessions/u-live/sleep", None)]

            app.calls.clear()
            await pilot.press("R")
            await pilot.pause()
            assert app.acted() == []
            await pilot.press("A", "R")
            await pilot.pause()
            assert app.acted() == [("POST", "/api/v1/sessions/respawn",
                                    {"session_name": "carnivore_live", "confirm_restart_live": True})]
            app.calls.clear()
            await pilot.press("R")
            await pilot.pause()
            assert app.acted() == []

            await pilot.press("A", "j")
            await pilot.press("k", "R")
            await pilot.pause()
            assert app.acted() == []

            await pilot.press("j", "R")
            await pilot.pause()
            assert app.acted() == [("POST", "/api/v1/sessions/respawn",
                                    {"session_name": "carnivore_gone", "confirm_restart_live": False})]

            app.calls.clear()
            n_ran = len(ran)
            await pilot.press("j", "enter", "s", "R", "u", "A")
            await pilot.pause()
            assert app.acted() == [] and len(ran) == n_ran

            await pilot.press("k", "k", "n")
            await pilot.pause()
            options = app.screen.query_one(OptionList)
            assert options.highlighted == 1
            await pilot.press("enter")
            await pilot.pause()
            assert app.acted()[-1] == ("POST", "/api/v1/sessions",
                                       {"auto_start_claude": True, "working_dir": "/w/live", "agent_type": "p2"})
    asyncio.run(run())


def test_attach_plan_argv() -> None:
    outside = attach.plan_attach("n", "cloude", {"TMUX": "/tmp/tmux-1/other,1,0", "PATH": "/x"})
    assert outside.suspend and "TMUX" not in outside.env
    assert outside.argvs[0][-5:] == ("attach-session", "-f", "ignore-size", "-t", "=n")
    inside = attach.plan_attach("n", "cloude", {"TMUX": "/tmp/tmux-1/cloude,1,0"})
    assert not inside.suspend
    assert inside.argvs[0][-3:] == ("refresh-client", "-f", "ignore-size") and inside.argvs[1][-3:] == ("switch-client", "-t", "=n")


def _winsize(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


@pytest.mark.skipif(shutil.which("tmux") is None, reason="needs tmux")
def test_real_attach_on_throwaway_socket(tmp_path: Any) -> None:
    sock = TEST_SOCKET_NAME
    assert sock != "cloude"
    base = tmux_argv_prefix(sock)

    def tmux(*args: str) -> str:
        return subprocess.run([*base, *args], capture_output=True, text=True, check=False).stdout.strip()

    try:
        subprocess.run([*base, "new-session", "-d", "-s", "manual_one", "-x", "132", "-y", "40"], check=True)
        tmux("set-option", "-t", "manual_one", "window-size", "manual")
        plan = attach.plan_attach("manual_one", sock, {"PATH": os.environ["PATH"]})
        pid, fd = pty.fork()
        if pid == 0:
            os.execvpe(plan.argvs[0][0], list(plan.argvs[0]), dict(plan.env, TERM="xterm"))
        _winsize(fd, 20, 60)
        size = ""
        for _ in range(40):
            time.sleep(0.1)
            if select.select([fd], [], [], 0)[0]:
                os.read(fd, 65536)
            if tmux("list-clients", "-t", "manual_one"):
                size = tmux("display-message", "-p", "-t", "manual_one", "#{window_width}x#{window_height}")
                break
        assert size == "132x40", size
        _winsize(fd, 30, 90)
        os.kill(pid, signal.SIGWINCH)
        time.sleep(0.5)
        assert tmux("display-message", "-p", "-t", "manual_one", "#{window_width}x#{window_height}") == "132x40"
        os.write(fd, b"\x02d")
        deadline, status = time.time() + 5, None
        while time.time() < deadline and status is None:
            if select.select([fd], [], [], 0)[0]:
                with contextlib.suppress(OSError):
                    os.read(fd, 65536)
            done, st = os.waitpid(pid, os.WNOHANG)
            status = st if done else None
            time.sleep(0.05)
        assert status == 0, status
    finally:
        tmux("kill-session", "-t", "=manual_one")
