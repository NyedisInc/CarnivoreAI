
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_tl_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_tl_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from websockets.asyncio.server import unix_serve  # noqa: E402

from src.api.websocket import router  # noqa: E402
from src.core.federation import peer_links, peer_terminal_proxy as proxy  # noqa: E402
from src.core.federation.peer_client import Route  # noqa: E402
from tests.socket_guard import TEST_SOCKET_NAME  # noqa: E402
from tests.python.computers.test_tls_link import _down, _linked, _up, world  # noqa: E402,F401
from tests.test_ws_subprotocol_auth import _mint_token, patched_auth_config  # noqa: E402,F401

HOST_KEY, TMUX_NAME, PEER_TOKEN = "peer-tlsmember", "member_pane", "PEER.TOKEN-never-reaches-the-browser"
WIRE = f"remote:{HOST_KEY}:{TMUX_NAME}"


def _tmux(sock: str, *args: str) -> str:
    return subprocess.run(["tmux", "-L", TEST_SOCKET_NAME, *args], capture_output=True, text=True, timeout=10, check=False).stdout


async def _member_terminal(root: Path, sock: str):
    async def handle(ws) -> None:
        await ws.send(json.dumps({"type": "terminal.ready", "startup_command": "none"}))
        async for frame in ws:
            if isinstance(frame, bytes):
                _tmux(sock, "send-keys", "-t", TMUX_NAME, "-l", frame.decode())
                await asyncio.sleep(0.4)
                await ws.send(_tmux(sock, "capture-pane", "-p", "-t", TMUX_NAME).encode())

    path = str(root / "member.sock")
    os.unlink(path)
    return await unix_serve(handle, path, subprotocols=["cloude.jwt.v1"])


@pytest.mark.asyncio
async def test_keys_typed_in_the_browser_reach_the_members_pane_and_its_output_returns_over_the_tls_link(world, monkeypatch):  # noqa: F811
    root, _dirs, _idents = world
    sock = os.path.join(tempfile.mkdtemp(prefix="tt", dir="/tmp"), "t.sock")
    up = await _up(world)
    terminal = None
    try:
        await _linked(up)
        back_path = json.loads(next(s for s in up.seen if s[1] == "/federation/link")[2])["path"]
        assert Path(back_path).name.startswith("in-")
        up.stubs[1].close()
        await up.stubs[1].wait_closed()
        _tmux(sock, "new-session", "-d", "-s", TMUX_NAME, "-x", "100", "-y", "30", "sh")
        assert TMUX_NAME in _tmux(sock, "list-sessions")
        terminal = await _member_terminal(root, sock)

        class Client:
            route = Route("unix", back_path)

            async def bearer(self, force: bool = False) -> str:
                return PEER_TOKEN

        monkeypatch.setattr(peer_links, "LINKS", SimpleNamespace(connected_clients=lambda: [("member-install-bbbb", Client())]))
        monkeypatch.setattr(proxy.peer_auth, "open_db", lambda: SimpleNamespace(close=lambda: None))
        monkeypatch.setattr(proxy.peer_hosts, "get", lambda _c, iid: SimpleNamespace(key=HOST_KEY))
        app = FastAPI()
        app.include_router(router)
        app.state.session_manager = SimpleNamespace()
        app.state.services = SimpleNamespace(registry=SimpleNamespace(sessions={}))
        app.state.local_servers = SimpleNamespace()
        app.state.log_monitor = SimpleNamespace()

        def browser() -> tuple:
            seen, blob = [], b""
            with TestClient(app).websocket_connect(f"/ws/terminal?session_id={WIRE}", subprotocols=["cloude.jwt.v1", _mint_token()]) as ws:
                while json.loads(ws.receive_text()).get("type") != "terminal.ready":
                    pass
                ws.send_bytes(b"echo $((6*7))-tls-link-ok\r")
                while b"42-tls-link-ok" not in blob:
                    blob += ws.receive_bytes()
                seen.append(ws.accepted_subprotocol)
            return seen, blob

        seen, blob = await asyncio.wait_for(asyncio.to_thread(browser), 30)
        assert b"42-tls-link-ok" in blob and seen == ["cloude.jwt.v1"]
        assert PEER_TOKEN.encode() not in blob
        assert "42-tls-link-ok" in _tmux(sock, "capture-pane", "-p", "-t", TMUX_NAME)
    finally:
        if terminal is not None:
            terminal.close()
        _tmux(sock, "kill-server")
        shutil.rmtree(os.path.dirname(sock), ignore_errors=True)
        await _down(up)
