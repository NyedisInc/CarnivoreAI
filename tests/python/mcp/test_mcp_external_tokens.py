
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.config.mcp import McpConfig
from src.core.mcp import pending, token_store, tools, write_tools
from src.main import app
from dataclasses import replace

from src.cplugs.host import runtime, state as owner_state
from src.cplugs.host import developer_mode
from src.cplugs.host import mcp as cplug_mcp
from tests.python.cplugs.owner import isolated_host
from tests.python.mcp.test_mcp_endpoint import _rpc
from tests.python.mcp.test_mcp_write import WriteManager, seed_crosstalk_directory


PLUGINS_WITH_TOOLS = ("huddle", "reviewboard", "tmdevtools")


@pytest.fixture
def env(monkeypatch, tmp_path):
    mgr = WriteManager(tmp_path)
    seed_crosstalk_directory(monkeypatch, tmp_path)
    cfg = McpConfig(gate_cross_session_actions=False)
    store = token_store.TokenStore(tmp_path)
    monkeypatch.setattr(app.state, "session_manager", mgr, raising=False)
    monkeypatch.setattr("src.api.mcp_routes.settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(mcp=cfg)))
    monkeypatch.setattr(write_tools, "gate_enabled", lambda: cfg.gate_cross_session_actions)
    monkeypatch.setattr(token_store, "get_store", lambda: store)
    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    monkeypatch.setattr(pending, "MAX_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(write_tools, "_created", {})
    mgr.wire_panes(monkeypatch)
    monkeypatch.setattr(developer_mode, "is_on", lambda: True)
    isolated_host(monkeypatch, app, tmp_path, on=PLUGINS_WITH_TOOLS)
    yield TestClient(app, client=("127.0.0.1", 50000), raise_server_exceptions=False), mgr, store, cfg


def _h(secret):
    return {"Authorization": f"Bearer {secret}"}


def _rpc_call(client, secret, method, params=None):
    r = client.post("/mcp", json=_rpc(method, params), headers=_h(secret))
    assert r.status_code == 200, r.text
    return r.json()


def _tool(client, secret, name, args=None):
    return _rpc_call(client, secret, "tools/call", {"name": name, "arguments": args or {}})["result"]


def test_minted_token_authenticates_and_only_a_hash_is_stored(env, tmp_path):
    client, _, store, _ = env
    row, secret = store.mint("claude desktop", "read")
    assert secret.startswith("cmcp_") and len(secret) > 40
    assert _tool(client, secret, "whoami")["content"][0]["text"] == json.dumps({"external_client": "claude desktop", "scope": "read", "hidden_families": []})
    raw = (tmp_path / token_store.FILE_NAME).read_text()
    assert secret not in raw and secret[5:] not in raw and "hash" in raw
    assert oct((tmp_path / token_store.FILE_NAME).stat().st_mode & 0o777) == "0o600"
    assert store.list()[0]["last_used_at"] is not None and "hash" not in store.list()[0]
    again = token_store.TokenStore(tmp_path)
    assert again.authenticate(secret)["name"] == "claude desktop"


def test_revoked_and_expired_and_unknown_tokens_are_refused(env):
    client, _, store, _ = env
    row, secret = store.mint("a", "read")
    ok = client.post("/mcp", json=_rpc("ping"), headers=_h(secret))
    assert ok.status_code == 200
    store.revoke(row["id"])
    assert client.post("/mcp", json=_rpc("ping"), headers=_h(secret)).status_code == 401
    clock = [1000.0]
    timed = token_store.TokenStore(store._dir, clock=lambda: clock[0])
    monkey_row, s2 = timed.mint("b", "read", expires_in_days=1)
    assert timed.authenticate(s2) is not None
    clock[0] += 86401
    assert timed.authenticate(s2) is None
    assert client.post("/mcp", json=_rpc("ping"), headers=_h("cmcp_" + "x" * 43)).status_code == 401


def test_read_token_sees_and_calls_only_read_tools(env):
    client, _, store, _ = env
    _, secret = store.mint("r", "read")
    names = {t["name"] for t in _rpc_call(client, secret, "tools/list")["result"]["tools"]}
    assert "sessions_list" in names and names.isdisjoint(tools.WRITE_TOOLS)
    out = _tool(client, secret, "session_stop", {"target": "cloude_b"})
    assert out["isError"] is True and "read-only" in out["content"][0]["text"]
    assert pending.get_store().list() == []


def test_every_write_from_a_write_token_goes_to_the_inbox_even_with_the_gate_off(env):
    client, mgr, store, cfg = env
    _, secret = store.mint("script", "write")
    assert cfg.gate_cross_session_actions is False
    names = {t["name"] for t in _rpc_call(client, secret, "tools/list")["result"]["tools"]}
    assert {n for n in tools.WRITE_TOOLS - {"notify"} if cplug_mcp.available(n)} <= names
    for name, args in [("session_stop", {"target": "cloude_b"}), ("session_send_keys", {"target": "cloude_b", "text": "hi"}),
                       ("session_restart", {"target": "cloude_b"}), ("session_send_message", {"target": "cloude_b", "text": "yo"}),
                       ("session_notes_put", {"target": "cloude_b", "body": "x", "expected_revision": 0})]:
        out = _tool(client, secret, name, args)
        assert json.loads(out["content"][0]["text"])["status"] == "pending", name
    rows = pending.get_store().list()
    assert len(rows) == 5 and {r["external_client"] for r in rows} == {"script"}
    assert mgr.sent == [] and mgr.respawns == []
    capped = _tool(client, secret, "session_create", {"working_dir": "/tmp"})
    assert capped["isError"] is True and "waiting on the owner" in capped["content"][0]["text"]
    cards = asyncio.run(pending.AgentActionProvider(pending.get_store(), lambda: mgr).items())
    assert cards and all(c["external_client"] == "script" for c in cards)


def test_a_write_token_sees_a_plugins_tools_only_while_that_plugin_is_on(env):
    client, _, store, _ = env
    _, secret = store.mint("phone", "write")
    reviewboard_writes = {"task_manager_board_create", "task_manager_scratch_post"}

    def listed() -> set:
        return {t["name"] for t in _rpc_call(client, secret, "tools/list")["result"]["tools"]}

    assert reviewboard_writes | {"task_manager_dev_fold_set"} <= listed()
    manifest = runtime.find("reviewboard").manifest
    owner_state.update(runtime.current().state_dir, manifest, None, lambda st: replace(st, enabled=False))
    assert listed().isdisjoint(reviewboard_writes)
    refused = _tool(client, secret, "task_manager_scratch_post", {"name": "x"})
    assert refused["isError"] is True and "plugin is disabled" in refused["content"][0]["text"]


def test_approval_runs_the_original_action_and_wait_returns_it(env):
    client, mgr, store, _ = env
    _, secret = store.mint("script", "write")
    answer = json.loads(_tool(client, secret, "session_send_keys", {"target": "cloude_b", "text": "hello"})["content"][0]["text"])
    app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
    try:
        assert client.post(f"/api/v1/agent-actions/{answer['id']}/approve").status_code == 200
    finally:
        app.dependency_overrides.pop(require_auth, None)
    assert mgr.sent and "hello" in str(mgr.sent[0][1])
    waited = _tool(client, secret, "approval_wait", {"id": answer["id"]})
    assert "isError" not in waited
    _, other = store.mint("other", "write")
    assert _tool(client, other, "approval_wait", {"id": answer["id"]})["isError"] is True


def test_existing_refusals_hold_for_tokens(env):
    client, mgr, store, _ = env
    _, secret = store.mint("t", "write")
    body = _rpc("ping")
    remote = TestClient(app, client=("192.168.1.9", 5000), raise_server_exceptions=False)
    assert remote.post("/mcp", json=body, headers=_h(secret)).status_code == 403
    assert client.post("/mcp", json=body, headers={**_h(secret), "Origin": "http://x.example"}).status_code == 403
    assert client.post("/mcp", json=body, headers={**_h(secret), "X-Forwarded-For": "8.8.8.8"}).status_code == 403
    assert client.post("/mcp", json=body, headers={**_h(secret), "Forwarded": ""}).status_code == 403
    assert client.post("/mcp", json=body, headers=_h("not-a-token-and-not-a-hook-token")).status_code == 401
    assert client.post("/mcp", json=body, headers=_h(mgr.token_a)).status_code == 401
    assert client.post("/mcp", json=body, headers={"Authorization": f"Bearer {mgr.token_a}", "X-Carnivore-Session": "ses_a"}).status_code == 200


def test_via_link_refuses_a_valid_token_and_the_admin_routes(env):
    client, _, store, _ = env
    _, secret = store.mint("t", "write")

    async def linked(scope, receive, send):
        scope["via_link"] = True
        await app(scope, receive, send)

    over_link = TestClient(linked, client=("127.0.0.1", 50000), raise_server_exceptions=False)
    assert over_link.post("/mcp", json=_rpc("ping"), headers=_h(secret)).status_code == 403
    app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
    try:
        for method, path in [("get", "/api/v1/mcp-admin"), ("get", "/api/v1/mcp-admin/tokens"), ("post", "/api/v1/mcp-admin/tokens"),
                             ("delete", "/api/v1/mcp-admin/tokens/tok_x"), ("put", "/api/v1/mcp-admin/settings")]:
            assert getattr(over_link, method)(path).status_code == 403, path
    finally:
        app.dependency_overrides.pop(require_auth, None)


def test_admin_routes_need_the_owner_login(env):
    client, mgr, store, _ = env
    _, secret = store.mint("t", "write")
    for headers in ({}, _h(secret), _h(mgr.token_a)):
        assert client.get("/api/v1/mcp-admin/tokens", headers=headers).status_code == 401
        assert client.post("/api/v1/mcp-admin/tokens", json={"name": "n", "scope": "read"}, headers=headers).status_code == 401
        assert client.delete("/api/v1/mcp-admin/tokens/x", headers=headers).status_code == 401


def test_owner_mints_lists_and_revokes_over_the_routes(env):
    client, _, store, _ = env
    app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
    try:
        made = client.post("/api/v1/mcp-admin/tokens", json={"name": "desk", "scope": "read", "expires_in_days": 30})
        assert made.status_code == 201
        secret, tid = made.json()["secret"], made.json()["token"]["id"]
        listed = client.get("/api/v1/mcp-admin/tokens").json()["tokens"]
        assert [t["name"] for t in listed] == ["desk"] and secret not in json.dumps(listed)
        assert client.post("/api/v1/mcp-admin/tokens", json={"name": "DESK", "scope": "read"}).status_code == 422
        assert client.post("/api/v1/mcp-admin/tokens", json={"name": "x", "scope": "admin"}).status_code == 400
        status = client.get("/api/v1/mcp-admin").json()
        assert status["endpoint"].endswith("/mcp") and {t["name"] for t in status["tools"]} >= {"sessions_list", "session_stop"}
        assert next(t for t in status["tools"] if t["name"] == "session_stop")["write"] is True
        assert client.post("/mcp", json=_rpc("ping"), headers=_h(secret)).status_code == 200
        assert client.delete(f"/api/v1/mcp-admin/tokens/{tid}").status_code == 200
        assert client.delete(f"/api/v1/mcp-admin/tokens/{tid}").status_code == 404
        assert client.post("/mcp", json=_rpc("ping"), headers=_h(secret)).status_code == 401
    finally:
        app.dependency_overrides.pop(require_auth, None)


def test_initialize_returns_the_guide_scoped_to_the_token(env):
    client, _, store, _ = env
    _, w = store.mint("w", "write")
    _, r = store.mint("r", "read")
    wide = _rpc_call(client, w, "initialize", {"protocolVersion": "2025-06-18"})["result"]["instructions"]
    narrow = _rpc_call(client, r, "initialize", {"protocolVersion": "2025-06-18"})["result"]["instructions"]
    assert "approval_wait" in wide and "remote:peer-" in wide and "read-only" not in wide
    assert "read-only" in narrow and "approval_wait" not in narrow and "sessions_list" in narrow
