
from __future__ import annotations

import base64
import asyncio
import os
import tempfile
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mcp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mcp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from fastapi.testclient import TestClient  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402

from src.api.agent_auth import require_agent  # noqa: E402
from src.config.mcp import McpConfig  # noqa: E402
from src.core.mcp import protocol, tools  # noqa: E402
from src.core.sessions.hook_token_authority import HookTokenAuthority  # noqa: E402
from src.cplugs.host import mcp as mcp_host  # noqa: E402
from src.main import app  # noqa: E402
from src.models import Session, SessionInfo  # noqa: E402
from tests.python.cplugs.owner import isolated_host

SECRET = "ghp_" + "aB3xY9" * 6
KEY_BODY = [base64.b64encode(os.urandom(48)).decode() for _ in range(4)]
KEY_TEXT = "\n".join(
    ["filler"] * 10
    + ["-----BEGIN OPENSSH PRIVATE KEY-----"] + KEY_BODY + ["-----END OPENSSH PRIVATE KEY-----"]
    + ["after1", "after2", "after3"]
)


def _info(sid: str, tmux: str) -> SessionInfo:
    return SessionInfo(
        session=Session(id=sid, working_dir="/tmp/x"), tmux_session=tmux, label=tmux
    )


class FakeManager:

    def __init__(self, tmp_path) -> None:
        self.key_mode = False
        self.hook_tokens = HookTokenAuthority(lambda: tmp_path)
        self.token_a = self.hook_tokens.mint("ses_a", tmux_name="cloude_a")
        self.token_b = self.hook_tokens.mint("ses_b", tmux_name="cloude_b")
        self.infos = [_info("ses_a_row2", "cloude_a"), _info("ses_b", "cloude_b")]
        self._registry = SimpleNamespace(
            registered_ids_for_tmux_name=lambda name: [
                i.session.id for i in self.infos if i.tmux_session == name
            ]
        )

    async def list_session_infos(self):
        return self.infos

    def capture_scrollback(self, lines=3000, session_id=None) -> bytes:
        assert session_id is not None
        if session_id == "ses_b" and self.key_mode:
            return KEY_TEXT.encode()
        return f"\x1b[31mline\x1b[0m token={SECRET}\n".encode() * 3


@pytest.fixture
def env(monkeypatch, tmp_path):
    mgr = FakeManager(tmp_path)
    cfg = McpConfig()
    monkeypatch.setattr(app.state, "session_manager", mgr, raising=False)
    isolated_host(monkeypatch, app, tmp_path)
    monkeypatch.setattr(
        "src.api.mcp_routes.settings",
        SimpleNamespace(load_auth_config=lambda: SimpleNamespace(mcp=cfg)),
    )
    monkeypatch.setattr("src.core.notifications.agent_message.settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(mcp=cfg)))
    return TestClient(app, client=("127.0.0.1", 50000), raise_server_exceptions=False), mgr, cfg


def _hdr(mgr, sid="ses_a", token=None):
    return {"Authorization": f"Bearer {token or mgr.token_a}", "X-Carnivore-Session": sid}


def _rpc(method, params=None, msg_id=1):
    body = {"jsonrpc": "2.0", "method": method}
    if msg_id is not None:
        body["id"] = msg_id
    if params is not None:
        body["params"] = params
    return body


def _call(client, mgr, name, args=None):
    r = client.post("/mcp", json=_rpc("tools/call", {"name": name, "arguments": args or {}}), headers=_hdr(mgr))
    assert r.status_code == 200, r.text
    return r.json()["result"]


def test_handshake(env):
    client, mgr, _ = env
    r = client.post("/mcp", json=_rpc("server/discover"), headers=_hdr(mgr))
    assert r.status_code == 200 and r.json()["error"]["code"] == -32601
    r = client.post("/mcp", json=_rpc("initialize", {"protocolVersion": "2025-06-18"}), headers=_hdr(mgr))
    assert r.json()["result"]["protocolVersion"] == "2025-06-18"
    assert r.headers["mcp-session-id"]
    r = client.post("/mcp", json=_rpc("initialize", {"protocolVersion": "1999-01-01"}), headers=_hdr(mgr))
    assert r.json()["result"]["protocolVersion"] == "2025-11-25"
    r = client.post("/mcp", json=_rpc("notifications/initialized", msg_id=None), headers=_hdr(mgr))
    assert r.status_code == 202 and r.content == b""
    r = client.post("/mcp", json=_rpc("tools/list"), headers=_hdr(mgr))
    assert {t["name"] for t in r.json()["result"]["tools"]} == {n for n in tools._TOOLS if mcp_host.available(n)}
    assert client.get("/mcp").status_code == 405
    assert client.delete("/mcp").status_code == 405
    r = client.post("/mcp", json=[_rpc("ping", msg_id=1), _rpc("ping", msg_id=2)], headers=_hdr(mgr))
    assert [m["id"] for m in r.json()] == [1, 2]


SWARM_TOOLS = {f"swarm_{n}" for n in (
    "accept_report", "agent", "answer", "ask", "checkpoints", "conversation", "conversations", "pass",
    "promote", "propose_naming", "remember", "report", "rewind", "roster", "say", "spawn", "suggest")}


def test_tools_list_names_every_swarm_tool_and_no_swarm_tool(env):
    client, mgr, _ = env
    r = client.post("/mcp", json=_rpc("tools/list"), headers=_hdr(mgr))
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert len(names) > len(SWARM_TOOLS)
    assert SWARM_TOOLS <= names
    from src.core.mcp import pack_machines_tools, pack_placement_tools, pack_relay_tools, pack_skills_tools, pack_span_tools, pack_transport_tools, pack_migrate_tools, pack_move_tools
    machine_tools = {n for mod in (pack_machines_tools, pack_placement_tools, pack_relay_tools, pack_skills_tools, pack_span_tools, pack_transport_tools, pack_migrate_tools, pack_move_tools) for n in (*mod.READ_TOOLS, *mod.WRITE_TOOLS)}
    from src.core.mcp import merged_tools

    machine_tools |= set(merged_tools.MERGED)
    assert sorted(n for n in names if n.startswith("pack_") and n not in machine_tools) == []

def test_pane_auth_waits_for_registration_but_rechecks_its_token(env):
    _, mgr, _ = env
    mgr.infos.clear()

    def request(token: str) -> Request:
        return Request({"type": "http", "method": "POST", "path": "/mcp", "app": app,
                        "client": ("127.0.0.1", 50000),
                        "headers": [(b"authorization", f"Bearer {token}".encode()),
                                    (b"x-carnivore-session", b"ses_a")]})

    async def run() -> None:
        ready = asyncio.Event()
        mgr._pending_agent_registration = {"ses_a": ("cloude_a", ready)}
        caller_task = asyncio.create_task(require_agent(request(mgr.token_a)))
        await asyncio.sleep(0)
        assert not caller_task.done()
        with pytest.raises(HTTPException) as invalid:
            await require_agent(request("wrong-token"))
        assert invalid.value.status_code == 401
        mgr.infos.append(_info("ses_a_row2", "cloude_a"))
        ready.set()
        caller = await caller_task
        assert caller.current_session_id == "ses_a_row2"

        mgr.infos.clear()
        failed = asyncio.Event()
        mgr._pending_agent_registration = {"ses_a": ("cloude_a", failed)}
        failed_task = asyncio.create_task(require_agent(request(mgr.token_a)))
        await asyncio.sleep(0)
        assert not failed_task.done()
        assert mgr.hook_tokens.release("ses_a", tmux_name="cloude_a")
        mgr.infos.append(_info("ses_other", "cloude_a"))
        failed.set()
        with pytest.raises(HTTPException) as revoked:
            await failed_task
        assert revoked.value.status_code == 401

    asyncio.run(run())


def test_whoami_resolves_the_current_row(env):
    client, mgr, _ = env
    body = _call(client, mgr, "whoami")
    assert "isError" not in body
    text = body["content"][0]["text"]
    assert "ses_a_row2" in text and "cloude_a" in text


def test_target_is_required_and_never_defaults(env):
    client, mgr, _ = env
    for name in ("session_status", "session_read_output", "session_notes_get"):
        body = _call(client, mgr, name)
        assert body["isError"] is True and "target is required" in body["content"][0]["text"]
    assert _call(client, mgr, "session_status", {"target": "nope"})["isError"] is True


def test_read_output_strips_ansi_and_redacts(env):
    client, mgr, _ = env
    body = _call(client, mgr, "session_read_output", {"target": "cloude_b", "lines": 2})
    text = body["content"][0]["text"]
    assert SECRET not in text and "\\u001b" not in text and "****" in text


def test_private_key_body_never_survives_a_tail_window(env):
    client, mgr, _ = env
    mgr.key_mode = True
    body = _call(client, mgr, "session_read_output", {"target": "ses_b", "lines": 7})
    text = body["content"][0]["text"]
    assert "after3" in text
    for line in KEY_BODY:
        assert line not in text and line[:16] not in text


def test_note_body_is_redacted(env):
    from src.core.mcp.tools import redact_text

    assert SECRET not in redact_text(f"note {SECRET} end")


def test_unbatched_listing_is_shared(env):
    client, mgr, _ = env
    calls = []
    real = mgr.list_session_infos

    async def counting():
        calls.append(1)
        return await real()

    mgr.list_session_infos = counting
    msgs = [_rpc("tools/call", {"name": "sessions_list"}, msg_id=i) for i in (1, 2, 3)]
    assert client.post("/mcp", json=msgs, headers=_hdr(mgr)).status_code == 200
    assert len(calls) == 1


def test_refusals(env):
    client, mgr, cfg = env
    body = _rpc("ping")
    assert client.post("/mcp", json=body).status_code == 401
    owner_jwt = {"Authorization": "Bearer not-a-hook-token"}
    assert client.post("/mcp", json=body, headers=owner_jwt).status_code == 401
    assert client.post("/mcp", json=body, headers={"Authorization": f"Bearer {mgr.token_a}"}).status_code == 401
    assert client.post("/mcp", json=body, headers=_hdr(mgr, sid="ses_zzz")).status_code == 401
    assert client.post("/mcp", json=body, headers=_hdr(mgr, sid="ses_b")).status_code == 401
    assert client.post("/mcp", json=body, headers=_hdr(mgr)).status_code == 200
    remote = TestClient(app, client=("192.168.1.9", 5000), raise_server_exceptions=False)
    assert remote.post("/mcp", json=body, headers=_hdr(mgr)).status_code == 403
    r = client.post("/mcp", json=body, headers={**_hdr(mgr), "Origin": "http://evil.example"})
    assert r.status_code == 403
    r = client.post("/mcp", json=body, headers={**_hdr(mgr), "X-Forwarded-For": "8.8.8.8"})
    assert r.status_code == 403
    r = client.post("/mcp", json=body, headers={**_hdr(mgr), "Forwarded": ""})
    assert r.status_code == 403
    r = client.post("/mcp", json=body, headers={**_hdr(mgr), "Origin": "http://127.0.0.1:8000"})
    assert r.status_code == 403
    mapped = TestClient(app, client=("::ffff:127.0.0.1", 5000), raise_server_exceptions=False)
    assert mapped.post("/mcp", json=body, headers=_hdr(mgr)).status_code == 200
    big = client.post("/mcp", content=b"x" * (protocol.MAX_BODY_BYTES + 1), headers=_hdr(mgr))
    assert big.status_code == 413
    deep = client.post("/mcp", content=b"[" * 100000, headers=_hdr(mgr))
    assert deep.status_code == 400
    cfg.enabled = False
    assert client.post("/mcp", json=body, headers=_hdr(mgr)).status_code == 404
    assert client.get("/mcp").status_code == 404


def test_invalid_mcp_config_block_reads_disabled():
    from src.config.auth_loader import _mcp_block

    assert _mcp_block(None).enabled is True
    assert _mcp_block({"enabled": False}).enabled is False
    assert _mcp_block({"enabled": "maybe"}).enabled is False
    assert _mcp_block("nonsense").enabled is False
