
from __future__ import annotations

import http.client
import json
import os
import socket
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mcp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mcp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

import uvicorn  # noqa: E402

from src.config.mcp import McpConfig  # noqa: E402
from src.core.mcp_health import first_hand  # noqa: E402
from src.core.mcp_health.first_hand import LINKS  # noqa: E402
from src.core.sessions.hook_token_authority import HookTokenAuthority  # noqa: E402
from src.main import app  # noqa: E402
from tests.python.cplugs.owner import isolated_host  # noqa: E402

TMUX = "carnivore_firsthand"


def _free_port(start: int = 5001) -> int:
    for port in range(start, start + 200):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("no free port")


def _post(port: int, token: str, body: dict) -> tuple[int, dict | None]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("POST", "/mcp", json.dumps(body), {
        "Content-Type": "application/json", "Authorization": f"Bearer {token}", "X-Carnivore-Session": "ses_fh",
    })
    reply = conn.getresponse()
    raw = reply.read()
    conn.close()
    return reply.status, (json.loads(raw) if raw else None)


@pytest.fixture
def server(monkeypatch, tmp_path):
    tokens = HookTokenAuthority(lambda: tmp_path)
    token = tokens.mint("ses_fh", tmux_name=TMUX)
    manager = SimpleNamespace(
        hook_tokens=tokens, _pending_agent_registration={},
        _registry=SimpleNamespace(registered_ids_for_tmux_name=lambda name: ["ses_fh"] if name == TMUX else []),
    )
    monkeypatch.setattr(app.state, "session_manager", manager, raising=False)
    isolated_host(monkeypatch, app, tmp_path)
    cfg = McpConfig()
    monkeypatch.setattr("src.api.mcp_routes.settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(mcp=cfg)))
    monkeypatch.setattr(first_hand, "PROCESS_BOOT_AT", datetime.now(timezone.utc) - timedelta(hours=1))
    LINKS.reset()
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off", log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not srv.started and time.time() < deadline:
        time.sleep(0.05)
    assert srv.started, "throwaway server did not start"
    yield port, token
    srv.should_exit = True
    thread.join(timeout=10)
    LINKS.reset()


def _listing_state() -> str:
    now = datetime.now(timezone.utc)
    return first_hand.carnivore_state(LINKS.seen(TMUX), started_at=now - timedelta(minutes=10), now=now, expects_server=True)


def test_connected_only_after_the_live_server_answered_the_session(server):
    port, token = server
    assert _listing_state() == "dropped"
    status, init = _post(port, token, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert status == 200 and init["result"]["serverInfo"]["name"] == "carnivore"
    status, listed = _post(port, token, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert status == 200 and listed["result"]["tools"], "a connected session must actually get its tools"
    assert _listing_state() == "connected"
    LINKS.reset()
    assert _listing_state() == "dropped"
    status, pong = _post(port, token, {"jsonrpc": "2.0", "id": 9, "method": "ping"})
    assert status == 200 and pong["result"] == {}
    assert _listing_state() == "connected"
    LINKS.reset()
    status, _ = _post(port, "wrong-token", {"jsonrpc": "2.0", "id": 3, "method": "initialize", "params": {}})
    assert status == 401 and LINKS.seen(TMUX) is None
