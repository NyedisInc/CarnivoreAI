
from __future__ import annotations

import json
import os
import tempfile
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_an_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_an_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from fastapi.testclient import TestClient  # noqa: E402
import structlog  # noqa: E402

from src.api.auth import require_auth  # noqa: E402
from src.config.mcp import McpConfig  # noqa: E402
from src.core import config_writer  # noqa: E402
from src.core.federation import peer_forward  # noqa: E402
from src.core.mcp import token_store, tools  # noqa: E402
from src.core.notifications import agent_message  # noqa: E402
from src.core.sessions.hook_token_authority import HookTokenAuthority  # noqa: E402
from src.main import app  # noqa: E402
from src.models import Session, SessionInfo  # noqa: E402
from tests.python.cplugs.owner import isolated_host  # noqa: E402
from tests.python.mcp.test_mcp_endpoint import _rpc  # noqa: E402

SECRET = "ghp_" + "aB3xY9" * 6
SENTINEL = "zq-sentinel-text-7731"


class FakeManager:

    def __init__(self, tmp_path) -> None:
        self.hook_tokens = HookTokenAuthority(lambda: tmp_path)
        self.token_a = self.hook_tokens.mint("ses_a", tmux_name="cloude_a")
        self.token_b = self.hook_tokens.mint("ses_b", tmux_name="cloude_b")
        self.infos = [SessionInfo(session=Session(id=i, working_dir="/tmp/x"), tmux_session=t, label=t)
                      for i, t in (("ses_a", "cloude_a"), ("ses_b", "cloude_b"))]
        self._registry = SimpleNamespace(registered_ids_for_tmux_name=lambda n: [
            i.session.id for i in self.infos if i.tmux_session == n])
        self.toasts: list[dict] = []

    async def list_session_infos(self):
        return self.infos

    def record_toast(self, session_id, kind, title, body=None, **kw):
        self.toasts.append({"session_id": session_id, "kind": kind, "title": title, "body": body, **kw})
        return SimpleNamespace(id=f"t{len(self.toasts)}", session_id=session_id,
                               model_dump_json=lambda: "{}")


@pytest.fixture
def env(monkeypatch, tmp_path):
    mgr, cfg = FakeManager(tmp_path), McpConfig()
    store = token_store.TokenStore(tmp_path)
    fake_settings = SimpleNamespace(load_auth_config=lambda: SimpleNamespace(mcp=cfg))
    monkeypatch.setattr(app.state, "session_manager", mgr, raising=False)
    monkeypatch.setattr("src.api.mcp_routes.settings", fake_settings)
    monkeypatch.setattr(agent_message, "settings", fake_settings)
    monkeypatch.setattr(token_store, "get_store", lambda: store)
    monkeypatch.setattr(agent_message, "_LIMITER", agent_message.Limiter())

    async def no_fanout(toast):
        return None
    monkeypatch.setattr(agent_message, "_broadcast", no_fanout)
    isolated_host(monkeypatch, app, tmp_path)
    return TestClient(app, client=("127.0.0.1", 50000), raise_server_exceptions=False), mgr, cfg, store


def _h(mgr, sid="ses_a", token=None):
    return {"Authorization": f"Bearer {token or mgr.token_a}", "X-Carnivore-Session": sid}


def _post(client, mgr, text, path_sid="ses_a", **kw):
    return client.post(f"/api/v1/sessions/{path_sid}/agent-message", json={"text": text}, headers=_h(mgr, **kw))


def _tool(client, mgr, text):
    r = client.post("/mcp", json=_rpc("tools/call", {"name": "notify", "arguments": {"text": text}}), headers=_h(mgr))
    return r.json()["result"]


def _names(client, headers):
    r = client.post("/mcp", json=_rpc("tools/list"), headers=headers)
    return {t["name"] for t in r.json()["result"]["tools"]}


def test_route_records_exactly_one_toast_for_the_callers_session(env):
    client, mgr, _, _ = env
    r = _post(client, mgr, "build is green")
    assert r.status_code == 201 and r.json() == {"sent": True, "toast_id": "t1"}
    assert len(mgr.toasts) == 1
    t = mgr.toasts[0]
    assert t["session_id"] == "ses_a" and t["notify_type"] == "agent.message" and t["body"] == "build is green"


def test_tool_uses_the_same_pipeline_and_names_the_callers_session(env):
    client, mgr, _, _ = env
    res = _tool(client, mgr, "done")
    assert not res.get("isError"), res
    assert len(mgr.toasts) == 1 and mgr.toasts[0]["session_id"] == "ses_a"
    assert "notify" in _names(client, _h(mgr))


def test_switch_off_hides_the_tool_and_refuses_tool_and_route(env):
    client, mgr, cfg, _ = env
    cfg.agent_notify = False
    assert "notify" not in _names(client, _h(mgr))
    res = _tool(client, mgr, "x")
    assert res["isError"] and "off" in res["content"][0]["text"]
    assert _post(client, mgr, "x").status_code == 403
    assert mgr.toasts == []
    cfg.agent_notify = True
    assert "notify" in _names(client, _h(mgr))


def test_secret_shaped_text_is_starred(env):
    client, mgr, _, _ = env
    assert _post(client, mgr, f"token {SECRET} leaked").status_code == 201
    body = mgr.toasts[0]["body"]
    assert SECRET not in body and "[redacted]" in body


def test_caps_and_control_character_strip(env):
    client, mgr, _, _ = env
    assert _post(client, mgr, "   \x00\x1b  ").status_code == 422
    long = _post(client, mgr, "a" * 281)
    assert long.status_code == 422 and long.json()["detail"]["code"] == "agent_notify_refused"
    assert _post(client, mgr, "a" * 280).status_code == 201
    assert _post(client, mgr, "he\x00l\x1blo\nworld").status_code == 201
    assert mgr.toasts[-1]["body"] == "hello world"


def test_limiter_windows_and_retry_after():
    now = [0.0]
    lim = agent_message.Limiter(clock=lambda: now[0])
    for _ in range(3):
        lim.check("s")
    with pytest.raises(agent_message.AgentNotifyError) as e:
        lim.check("s")
    assert e.value.status == 429 and 1 <= e.value.retry_after <= 61
    now[0] = 61.0
    lim.check("s")
    lim.check("s")
    now[0] = 130.0
    for _ in range(1):
        with pytest.raises(agent_message.AgentNotifyError) as e:
            lim.check("s")
    assert e.value.retry_after > 300
    now[0] = 700.0
    lim.check("s")
    lim.check("other")


def test_global_hourly_cap_across_sessions():
    now = [0.0]
    lim = agent_message.Limiter(clock=lambda: now[0])
    for i in range(30):
        now[0] = i * 100.0 % 3500
        lim.check(f"s{i}")
    with pytest.raises(agent_message.AgentNotifyError) as e:
        lim.check("s_new")
    assert e.value.status == 429
    now[0] = 3700.0
    lim.check("s_new")


def test_route_limited_gets_429_with_retry_after(env):
    client, mgr, _, _ = env
    for _ in range(3):
        assert _post(client, mgr, "hi").status_code == 201
    r = _post(client, mgr, "hi")
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    assert len(mgr.toasts) == 3
    res = _tool(client, mgr, "hi")
    assert res["isError"] and "retry in" in res["content"][0]["text"]


def test_external_and_read_scope_tokens_are_refused(env):
    client, mgr, _, store = env
    for scope in ("write", "read"):
        _, secret = store.mint(f"t{scope}", scope)
        h = {"Authorization": f"Bearer {secret}"}
        r = client.post("/api/v1/sessions/ses_a/agent-message", json={"text": "x"}, headers=h)
        assert r.status_code == 403
        assert "notify" not in _names(client, h)
        res = client.post("/mcp", json=_rpc("tools/call", {"name": "notify", "arguments": {"text": "x"}}), headers=h).json()["result"]
        assert res["isError"]
    assert mgr.toasts == []


def test_another_sessions_path_is_refused_and_no_credential_is_401(env):
    client, mgr, _, _ = env
    assert _post(client, mgr, "x", path_sid="ses_b").status_code == 403
    assert client.post("/api/v1/sessions/ses_a/agent-message", json={"text": "x"}).status_code == 401
    assert mgr.toasts == []


def test_audit_line_carries_length_never_the_text(env):
    client, mgr, _, _ = env
    with structlog.testing.capture_logs() as logs:
        assert _post(client, mgr, SENTINEL).status_code == 201
    sent = [e for e in logs if e["event"] == "agent_notify_sent"]
    assert len(sent) == 1 and sent[0]["session_id"] == "ses_a" and sent[0]["length"] == len(SENTINEL)
    assert SENTINEL not in json.dumps(logs, default=str)


def test_peer_forward_row_is_refuse():
    rows = [r for r in peer_forward.TABLE if r.path == "/sessions/{session_id}/agent-message"]
    assert len(rows) == 1 and rows[0].method == "POST" and rows[0].mode == peer_forward.REFUSE


def test_tool_registry_flags():
    assert "notify" in tools.WRITE_TOOLS and "notify" in tools._UNGATED_WRITES
    assert tools.has_tool("notify")


def test_admin_switch_route_writes_config_and_needs_owner(env, monkeypatch, tmp_path):
    client, mgr, _, _ = env
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text("{}")
    monkeypatch.setattr("src.api.mcp_admin_routes.settings", SimpleNamespace(
        auth_config_file=str(cfg_file), drop_auth_config_cache=lambda: None))
    assert client.put("/api/v1/mcp-admin/agent-notify", json={"enabled": False}, headers=_h(mgr)).status_code == 401
    app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
    try:
        r = client.put("/api/v1/mcp-admin/agent-notify", json={"enabled": False})
    finally:
        app.dependency_overrides.pop(require_auth, None)
    assert r.status_code == 200 and r.json() == {"enabled": False}
    assert json.loads(cfg_file.read_text())["mcp"]["agent_notify"] is False
    assert McpConfig().agent_notify is True


def test_pipeline_matches_the_real_record_toast_and_the_registry_row():
    import inspect
    from src.core.notifications import types as ntypes
    from src.core.session_manager import SessionManager

    assert "notify_type" in inspect.signature(SessionManager.record_toast).parameters
    row = next(r for r in ntypes.TYPES if r.id == "agent.message")
    assert row.match.carrier == agent_message.TOAST_KIND


def test_links_in_agent_text_are_defanged(env):
    client, mgr, _, _ = env
    assert _post(client, mgr, "open evil.click and https://x.example/a now").status_code == 201
    assert mgr.toasts[-1]["body"] == "open evil[.]click and hxxps://x[.]example/a now"
