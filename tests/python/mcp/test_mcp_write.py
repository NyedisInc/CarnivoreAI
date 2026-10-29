
from __future__ import annotations

import asyncio
import json
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.api.auth import require_auth
from src.config import settings
from src.config.mcp import McpConfig
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.crosstalk import store as crosstalk_store
from src.core.mcp import pending, protocol, write_tools
from src.core.mcp.caller import AgentCaller
from src.main import app
from src.models import Session, SessionInfo
from tests.python.mcp.test_mcp_endpoint import FakeManager, _call, _hdr, _info


class WriteManager(FakeManager):

    def __init__(self, tmp_path) -> None:
        super().__init__(tmp_path)
        self.sent: list = []
        self.respawns: list = []
        self.dialog = False
        self.gate_state = "ready"
        self.dead = False
        self.infos = [
            _info("ses_a_row2", "cloude_a").model_copy(update={"session_row_id": 11}),
            _info("ses_b", "cloude_b").model_copy(update={"session_row_id": 22}),
        ]

    async def send_input(self, data, session_id=None):
        self.sent.append((session_id, data))
        return True

    async def respawn_session(self, name, *, live_restart_confirmed=False, **_):
        self.respawns.append((name, live_restart_confirmed))
        return {"ok": True, "kind": "agent"}

    async def get_session_info(self, session_id=None):
        return SessionInfo(
            session=Session(id=session_id, working_dir="/tmp/x"), tmux_session="cloude_b",
            activity_status="question" if self.dialog else "idle", startup_gate=self.gate_state,
        )

    def wire_panes(self, monkeypatch):
        pasted = []
        mgr = self

        class Backend:
            def list_pane_status_all(self):
                return SimpleNamespace(ok=True, complete=True, reason=None, refused_rows=0, sessions=[
                    {"name": n, "pane_current_command": "node", "pane_dead": "1" if mgr.dead else "0"}
                    for n in ("cloude_a", "cloude_b")])

            async def paste_and_submit(self, text, gate=None):
                await gate()
                pasted.append(text)

        def find(sid):
            return next(i for i in mgr.infos if i.session.id == sid)

        registry = SimpleNamespace(
            get_session=lambda sid: SimpleNamespace(id=sid, tmux_session=find(sid).tmux_session, agent_type="claude"),
            get_backend=lambda sid: Backend(), subscribers={})
        monkeypatch.setattr(app.state, "services", SimpleNamespace(registry=registry), raising=False)
        return pasted


def seed_crosstalk_directory(monkeypatch: pytest.MonkeyPatch, state_dir: Path) -> None:
    ensure_db_migrated(state_dir)
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state_dir)
    with closing(connect(db_path_for(state_dir), create=False)) as conn:
        for row_id, name in ((11, "cloude_a"), (22, "cloude_b")):
            conn.execute(
                "INSERT INTO sessions (id, session_uuid, tmux_name, origin, created_at, updated_at) "
                "VALUES (?, ?, ?, 'observed', '2026-10-03T00:00:00Z', '2026-10-03T00:00:00Z')",
                (row_id, f"uuid-{row_id}", name),
            )


@pytest.fixture
def env(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    mgr = WriteManager(tmp_path)
    seed_crosstalk_directory(monkeypatch, tmp_path)
    cfg = McpConfig(gate_cross_session_actions=True)
    monkeypatch.setattr(app.state, "session_manager", mgr, raising=False)
    monkeypatch.setattr("src.api.mcp_routes.settings",
                        SimpleNamespace(load_auth_config=lambda: SimpleNamespace(mcp=cfg)))
    monkeypatch.setattr(write_tools, "gate_enabled", lambda: cfg.gate_cross_session_actions)
    monkeypatch.setattr("src.api.agent_action_routes.gate_enabled", lambda: cfg.gate_cross_session_actions)
    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    monkeypatch.setattr(pending, "MAX_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(write_tools, "_created", {})
    slept: list = []

    async def fake_sleep(state, session_uuid, **_):
        slept.append(session_uuid)
        return SimpleNamespace(status="asleep", detail="ok")

    monkeypatch.setattr("src.api.session_sleep_routes.sleep_by_uuid", fake_sleep)
    monkeypatch.setattr(write_tools, "_session_uuid_of_row", lambda row: f"uuid-{row}")
    mgr.wire_panes(monkeypatch)
    app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
    yield TestClient(app, client=("127.0.0.1", 50000), raise_server_exceptions=False), mgr, cfg, slept
    app.dependency_overrides.pop(require_auth, None)


def _text(result) -> str:
    return result["content"][0]["text"]


def test_gated_cross_session_stop_pends_then_approve_runs_it(env):
    client, mgr, _, slept = env
    body = _call(client, mgr, "session_stop", {"target": "cloude_b"})
    answer = json.loads(_text(body))
    assert answer["status"] == "pending" and not slept
    rows = client.get("/api/v1/agent-actions").json()["items"]
    assert [r["id"] for r in rows] == [answer["id"]]
    row = rows[0]
    assert row["action"] == "session_stop" and row["caller_tmux"] == "cloude_a"
    assert row["target_tmux"] == "cloude_b" and row["expires_at"] is None
    approved = client.post(f"/api/v1/agent-actions/{answer['id']}/approve")
    assert approved.status_code == 200 and slept == ["uuid-22"]
    assert client.post(f"/api/v1/agent-actions/{answer['id']}/approve").status_code == 409
    waited = _call(client, mgr, "approval_wait", {"id": answer["id"]})
    assert "isError" not in waited and "asleep" in _text(waited)
    assert client.get("/api/v1/agent-actions").json()["items"] == []


def test_deny_is_a_tool_error_and_runs_nothing(env):
    client, mgr, _, slept = env
    answer = json.loads(_text(_call(client, mgr, "session_stop", {"target": "cloude_b"})))
    assert client.post(f"/api/v1/agent-actions/{answer['id']}/deny").status_code == 200
    body = _call(client, mgr, "approval_wait", {"id": answer["id"]})
    assert body["isError"] is True and "denied" in _text(body) and not slept
    assert client.post("/api/v1/agent-actions/act_nope/deny").status_code == 404


def test_self_targeted_and_gate_off_are_ungated(env):
    client, mgr, cfg, slept = env
    assert "isError" not in _call(client, mgr, "session_stop", {"target": "cloude_a"})
    assert slept == ["uuid-11"] and pending.get_store().list() == []
    cfg.gate_cross_session_actions = False
    assert "isError" not in _call(client, mgr, "session_stop", {"target": "cloude_b"})
    assert slept[-1] == "uuid-22" and pending.get_store().list() == []


def test_approval_during_the_wait_returns_the_result_directly(env):
    _, mgr, _, _ = env
    view = protocol.BatchView(mgr, app)
    caller = AgentCaller(session_id="ses_a", tmux_name="cloude_a", current_session_id="ses_a_row2")

    async def keys():
        return await write_tools.session_send_keys(
            view, caller, {"target": "cloude_b", "text": "hi", "keys": ["Enter"]})

    async def run():
        task = asyncio.create_task(keys())
        while not pending.get_store().list():
            await asyncio.sleep(0.01)
        await pending.get_store().approve(pending.get_store().list()[0]["id"])
        return await task

    pending.MAX_WAIT_SECONDS = 5
    try:
        result = asyncio.run(run())
    finally:
        pending.MAX_WAIT_SECONDS = 0.05
    assert "sent_bytes" in _text(result) and mgr.sent == [("ses_b", "hi\r")]


def test_no_expiry_a_pending_action_waits_for_the_owner(env):
    client, mgr, _, slept = env
    clock = [1000.0]
    pending._store = pending.PendingActions(clock=lambda: clock[0])
    answer = json.loads(_text(_call(client, mgr, "session_stop", {"target": "cloude_b"})))
    clock[0] += 31 * 24 * 3600
    body = _call(client, mgr, "approval_wait", {"id": answer["id"], "timeout": 0})
    assert "isError" not in body and json.loads(_text(body))["status"] == "pending"
    assert client.post(f"/api/v1/agent-actions/{answer['id']}/approve").status_code == 200
    assert slept == ["uuid-22"]


def test_approval_wait_is_only_for_the_asking_agent(env):
    client, mgr, _, _ = env
    answer = json.loads(_text(_call(client, mgr, "session_stop", {"target": "cloude_b"})))
    r = client.post("/mcp", headers=_hdr(mgr, "ses_b", mgr.token_b), json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "approval_wait", "arguments": {"id": answer["id"]}}})
    assert r.json()["result"]["isError"] is True


def test_approved_restart_confirms_a_live_kill_only_if_still_live(env):
    client, mgr, _, _ = env
    answer = json.loads(_text(_call(client, mgr, "session_restart", {"target": "cloude_b"})))
    row = client.get("/api/v1/agent-actions").json()["items"][0]
    assert "KILLS the running agent" in row["args_summary"] and row["args"] == {"pane_live": True}
    client.post(f"/api/v1/agent-actions/{answer['id']}/approve")
    assert mgr.respawns == [("cloude_b", True)]
    mgr.dead = False
    answer = json.loads(_text(_call(client, mgr, "session_restart", {"target": "cloude_b"})))
    mgr.dead = True
    client.post(f"/api/v1/agent-actions/{answer['id']}/approve")
    assert len(mgr.respawns) == 1
    waited = _call(client, mgr, "approval_wait", {"id": answer["id"]})
    assert waited["isError"] is True and "changed" in _text(waited)
    answer = json.loads(_text(_call(client, mgr, "session_restart", {"target": "cloude_b"})))
    assert "KILLS" not in client.get("/api/v1/agent-actions").json()["items"][0]["args_summary"]
    client.post(f"/api/v1/agent-actions/{answer['id']}/approve")
    assert mgr.respawns[-1] == ("cloude_b", False)
    mgr.dead = False
    assert "isError" not in _call(client, mgr, "session_restart", {"target": "cloude_a"})
    assert mgr.respawns[-1] == ("cloude_a", False)


def test_keys_are_whitelisted_and_shown_escaped(env):
    client, mgr, _, _ = env
    for bad in ({"keys": ["Super-x"]}, {"text": "a\x03b"}, {"text": "a\x85b"}, {"text": "x" * 2000}, {}):
        body = _call(client, mgr, "session_send_keys", {"target": "cloude_a", **bad})
        assert body["isError"] is True
    _call(client, mgr, "session_send_keys", {"target": "cloude_b", "text": 'rm "x"', "keys": ["Enter"]})
    item = client.get("/api/v1/agent-actions").json()["items"][0]
    assert item["args"] == {"text": 'rm \\"x\\"', "keys": ["Enter"]}


def test_own_keys_into_an_open_dialog_go_to_the_inbox_whatever_the_setting(env):
    client, mgr, cfg, _ = env
    assert "isError" not in _call(client, mgr, "session_send_keys", {"target": "cloude_a", "keys": ["Enter"]})
    assert mgr.sent and not pending.get_store().list()
    mgr.sent.clear()
    cfg.gate_cross_session_actions = False
    for state in ("question", "awaiting_startup_prompt"):
        mgr.dialog, mgr.gate_state = state == "question", "ready" if state == "question" else state
        answer = json.loads(_text(_call(client, mgr, "session_send_keys", {"target": "cloude_a", "keys": ["Enter"]})))
        assert answer["status"] == "pending"
        pending.get_store().deny(answer["id"])
    assert not mgr.sent


def test_store_bounds_and_dedupe(env):
    client, mgr, _, _ = env
    a = json.loads(_text(_call(client, mgr, "session_stop", {"target": "cloude_b"})))
    b = json.loads(_text(_call(client, mgr, "session_stop", {"target": "cloude_b"})))
    assert a["id"] == b["id"] and len(pending.get_store().list()) == 1
    for n in range(4):
        _call(client, mgr, "session_send_keys", {"target": "cloude_b", "text": f"t{n}"})
    body = _call(client, mgr, "session_send_keys", {"target": "cloude_b", "text": "one too many"})
    assert body["isError"] is True and "waiting on the owner" in _text(body)
    store = pending.PendingActions()
    for n in range(pending.MAX_PENDING_TOTAL):
        store.create(caller_session_id="s", caller_tmux=f"c{n // 5}", target_session_id="t", target_tmux="t",
                     action="a", args_summary="x", execute=None, args={"n": n})
    with pytest.raises(pending.PendingLimitError):
        store.create(caller_session_id="s", caller_tmux="fresh", target_session_id="t", target_tmux="t",
                     action="a", args_summary="x", execute=None, args={"n": -1})


def test_only_the_first_gated_call_in_a_batch_waits(env, monkeypatch):
    client, mgr, _, _ = env
    waits = []
    real = pending.wait_for

    async def spy(item, timeout):
        waits.append(timeout)
        return await real(item, timeout)

    monkeypatch.setattr(pending, "wait_for", spy)
    calls = [{"jsonrpc": "2.0", "id": i, "method": "tools/call",
              "params": {"name": "session_send_keys", "arguments": {"target": "cloude_b", "text": f"t{i}"}}}
             for i in range(3)]
    assert client.post("/mcp", json=calls, headers=_hdr(mgr)).status_code == 200
    assert waits == [0.05, 0, 0]


def test_stop_refuses_when_the_id_now_points_at_another_pane(env):
    client, mgr, _, slept = env
    mgr.infos[1].session.tmux_created_epoch = 100
    answer = json.loads(_text(_call(client, mgr, "session_stop", {"target": "cloude_b"})))
    mgr.infos[1].session.tmux_created_epoch = 999
    client.post(f"/api/v1/agent-actions/{answer['id']}/approve")
    waited = _call(client, mgr, "approval_wait", {"id": answer["id"]})
    assert waited["isError"] is True and "different pane" in _text(waited) and not slept


def test_rename_repoints_the_hook_token_binding(tmp_path):
    from src.core.sessions.hook_token_authority import HookTokenAuthority

    authority = HookTokenAuthority(lambda: tmp_path)
    token = authority.mint("ses_x", tmux_name="cloude_old")
    authority.mint("ses_y", tmux_name="cloude_other")
    authority.rename_tmux("cloude_old", "cloude_new")
    assert authority.name_for("ses_x") == "cloude_new" and authority.name_for("ses_y") == "cloude_other"
    assert authority.verify("ses_x", token)
    reloaded = HookTokenAuthority(lambda: tmp_path)
    reloaded.load()
    assert reloaded.name_for("ses_x") == "cloude_new"


def test_agent_actions_show_in_the_approvals_inbox_and_clear_on_approve(env):
    from src.core.approvals.inbox import ApprovalsInbox

    client, mgr, _, _ = env
    frames: list = []
    inbox = ApprovalsInbox(frames.append, debounce=0)
    store = pending.get_store()
    inbox.register(pending.AgentActionProvider(store, lambda: mgr))
    store.subscribe(inbox.refresh)

    async def items():
        return await inbox.list_items()

    answer = json.loads(_text(_call(client, mgr, "session_send_keys", {"target": "cloude_b", "text": "hi"})))
    rows = asyncio.run(items())
    assert [r["id"] for r in rows] == [answer["id"]]
    row = rows[0]
    assert row["source"] == "agent_action" and row["session_id"] == "ses_b" and row["caller"] == "cloude_a"
    assert row["action"] == "session_send_keys" and row["args"]["text"] == "hi" and row["summary"]
    version = inbox.version
    assert version > 0 and frames
    client.post(f"/api/v1/agent-actions/{answer['id']}/approve")
    assert asyncio.run(items()) == [] and inbox.version > version


def test_approvals_route_lists_agent_actions(env, monkeypatch):
    from src.core.approvals.inbox import ApprovalsInbox

    client, mgr, _, _ = env
    inbox = ApprovalsInbox(lambda f: None, debounce=0)
    inbox.register(pending.AgentActionProvider(pending.get_store(), lambda: mgr))
    monkeypatch.setattr(app.state, "approvals_inbox", inbox, raising=False)
    monkeypatch.setattr("src.api.approvals_routes.peer_items.peer_items", lambda open_db: _empty())
    from src.api.peer_auth import require_peer_sessions
    app.dependency_overrides[require_peer_sessions] = lambda: SimpleNamespace(is_peer=False)
    try:
        answer = json.loads(_text(_call(client, mgr, "session_stop", {"target": "cloude_b"})))
        got = client.get("/api/v1/approvals").json()
        assert [i["id"] for i in got["items"]] == [answer["id"]]
        assert got["items"][0]["summary"]
        client.post(f"/api/v1/agent-actions/{answer['id']}/approve")
        assert client.get("/api/v1/approvals").json()["items"] == []
    finally:
        app.dependency_overrides.pop(require_peer_sessions, None)


async def _empty():
    return []


def _fake_create(monkeypatch, mgr):
    made = []

    async def fake_create(request, body):
        await asyncio.sleep(0)
        sid = f"ses_new{len(made)}"
        made.append(body)
        mgr.infos.append(_info(sid, f"cloude_new{len(made)}").model_copy(update={"session_row_id": 100 + len(made)}))
        return Session(id=sid, working_dir=body.working_dir)

    monkeypatch.setattr("src.api.session_crud_routes.create_session", fake_create)
    return made


def _create_call(i, wd, headers=None):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call",
            "params": {"name": "session_create", "arguments": {"working_dir": wd, "name": f"n{i}"}}}


def test_session_create_whitelist_and_caps(env, monkeypatch, tmp_path):
    client, mgr, _, _ = env
    made = _fake_create(monkeypatch, mgr)
    for bad in ({"working_dir": str(tmp_path), "command": "rm -rf /"},
                {"working_dir": str(tmp_path), "model": "x"}, {}, {"working_dir": "/nope/x"},
                {"working_dir": str(tmp_path), "project": "p"}):
        assert _call(client, mgr, "session_create", bad)["isError"] is True
    assert not made
    for _ in range(write_tools.MAX_CREATED_PER_AGENT):
        held = json.loads(_text(_call(client, mgr, "session_create", {"working_dir": str(tmp_path), "name": "n"})))
        assert held["status"] == "pending" and len(made) < write_tools.MAX_CREATED_PER_AGENT
        assert client.post(f"/api/v1/agent-actions/{held['id']}/approve").status_code == 200
    body = _call(client, mgr, "session_create", {"working_dir": str(tmp_path)})
    held = json.loads(_text(body))
    assert held["status"] == "pending"
    assert client.post(f"/api/v1/agent-actions/{held['id']}/approve").status_code == 200
    body = _call(client, mgr, "approval_wait", {"id": held['id']})
    assert body["isError"] is True and "limit 5" in _text(body)
    assert made[0].agent_type is None and made[0].label == "n"
    write_tools._created.update({f"o{i}": ("cloude_other", 0.0) for i in range(15)})
    mgr.infos.extend(_info(f"o{i}", f"cloude_o{i}") for i in range(15))
    r = client.post("/mcp", headers=_hdr(mgr, "ses_b", mgr.token_b), json=_create_call(1, str(tmp_path)))
    held = json.loads(r.json()["result"]["content"][0]["text"])
    assert held["status"] == "pending"
    assert client.post(f"/api/v1/agent-actions/{held['id']}/approve").status_code == 200
    result = pending.get_store().get(held['id']).result
    assert "limit 20" in _text(result)


def test_create_caps_hold_across_batches(env, monkeypatch, tmp_path):
    client, mgr, _, _ = env
    made = _fake_create(monkeypatch, mgr)
    for _batch in range(3):
        r = client.post("/mcp", headers=_hdr(mgr), json=[_create_call(i, str(tmp_path)) for i in range(20)])
        assert r.status_code == 200
    assert not made
    held = pending.get_store().list()
    assert len(held) <= 5
    for item in held:
        assert client.post(f"/api/v1/agent-actions/{item['id']}/approve").status_code == 200
    assert len(made) == write_tools.MAX_CREATED_PER_AGENT
    replies = r.json()
    assert all(m["result"].get("isError") or
               json.loads(_text(m["result"]))["status"] == "pending" for m in replies)


def test_prune_never_drops_an_id_recorded_after_the_listing():
    caller = AgentCaller(session_id="s", tmux_name="cloude_a", current_session_id="s")
    write_tools._created.clear()
    write_tools._created.update({"gone": ("cloude_a", 1.0), "fresh": ("cloude_a", 9.0)})
    assert write_tools._created_counts(set(), caller, listed_at=5.0) == (1, 1)
    assert list(write_tools._created) == ["fresh"]
    write_tools._created.clear()


def _wire_paste(monkeypatch, mgr, activity):
    mgr.dialog = activity == "question"
    return mgr.wire_panes(monkeypatch)


def test_send_message_waits_for_first_contact_and_never_answers_a_dialog(env, monkeypatch) -> None:
    client, mgr, _, _ = env
    pasted = _wire_paste(monkeypatch, mgr, "question")
    pending_body = json.loads(_text(_call(client, mgr, "session_send_message", {"target": "cloude_b", "text": "hello"})))
    assert pending_body["status"] == "pending" and not pasted
    action = pending.get_store().get(pending_body["id"])
    assert action.action == "crosstalk_send" and action.args == {"to": "ses_b", "text": "hello"}
    assert client.post(f"/api/v1/agent-actions/{pending_body['id']}/approve").status_code == 200
    receipt = json.loads(_text(action.result))
    stored = crosstalk_store.get(receipt["id"])
    assert stored["text"] == "hello" and stored["receiver_key"] == "uuid-22"
    assert stored["status"] == "queued" and not pasted
    pasted = _wire_paste(monkeypatch, mgr, "idle")
    body = _call(client, mgr, "session_send_message", {"target": "cloude_b", "text": "next"})
    second = json.loads(_text(body))
    assert "isError" not in body and second["id"] != receipt["id"]
    assert crosstalk_store.get(second["id"])["text"] == "next" and not pasted


def test_gate_setting_route_writes_through_config_writer(env, monkeypatch):
    client, _, _, _ = env
    written = {}

    def commit(path, mutate, **kw):
        written["doc"] = mutate({"mcp": {"enabled": True}, "other": 1})
        return SimpleNamespace(wrote=True)

    monkeypatch.setattr("src.api.agent_action_routes.config_writer.commit", commit)
    r = client.put("/api/v1/agent-actions/settings", json={"gate_cross_session_actions": False})
    assert r.status_code == 200
    assert written["doc"] == {"mcp": {"enabled": True, "gate_cross_session_actions": False}, "other": 1}
    assert client.get("/api/v1/agent-actions/settings").json() == {"gate_cross_session_actions": True}


def test_notes_put_needs_a_revision(env):
    client, mgr, _, _ = env
    body = _call(client, mgr, "session_notes_put", {"target": "cloude_b", "body": "x"})
    assert body["isError"] is True and "expected_revision" in _text(body)


def test_route_inventory_rows_are_guarded():
    from tests.test_route_auth_inventory import _http_routes

    rows = {(m, p): guarded for m, p, guarded in _http_routes()}
    for key in [("GET", "/api/v1/agent-actions"), ("GET", "/api/v1/agent-actions/settings"),
                ("PUT", "/api/v1/agent-actions/settings"),
                ("POST", "/api/v1/agent-actions/{action_id}/approve"),
                ("POST", "/api/v1/agent-actions/{action_id}/deny")]:
        assert rows.get(key) is True, key


def test_gate_reads_config_and_fails_closed(monkeypatch):
    from src.config import settings as real_settings

    def unreadable(self):
        raise ValueError("bad json")

    monkeypatch.setattr(type(real_settings), "load_auth_config", unreadable)
    assert write_tools.gate_enabled() is True
    monkeypatch.setattr(type(real_settings), "load_auth_config",
                        lambda self: SimpleNamespace(mcp=McpConfig(gate_cross_session_actions=False)))
    assert write_tools.gate_enabled() is False


def test_keys_show_the_whole_escaped_payload_and_different_tails_are_two_items(env):
    client, mgr, _, _ = env
    text = '"' * 500 + "a" * 400
    _call(client, mgr, "session_send_keys", {"target": "cloude_b", "text": text})
    _call(client, mgr, "session_send_keys", {"target": "cloude_b", "text": text[:-1] + "b"})
    items = client.get("/api/v1/agent-actions").json()["items"]
    assert len(items) == 2
    assert items[0]["args"]["text"] == '\\"' * 500 + "a" * 400
    _call(client, mgr, "session_send_keys", {"target": "cloude_b", "text": "x‮y"})
    shown = [i["args"]["text"] for i in client.get("/api/v1/agent-actions").json()["items"]]
    assert "x\\u202ey" in shown


def test_lone_surrogate_is_a_clear_tool_error(env):
    client, mgr, _, _ = env
    body = _call(client, mgr, "session_send_keys", {"target": "cloude_b", "text": "a\ud800b"})
    assert body["isError"] is True and "surrogate" in _text(body)


def test_wait_for_keeps_waiting_while_an_approved_action_runs():
    store = pending.PendingActions()

    async def slow():
        await asyncio.sleep(0.3)
        return {"content": [], "done": True}

    item = store.create(caller_session_id="s", caller_tmux="c", target_session_id="t", target_tmux="t",
                        action="a", args_summary="x", execute=slow)

    async def run():
        approve = asyncio.create_task(store.approve(item.id))
        await asyncio.sleep(0.05)
        status = await pending.wait_for(item, 2)
        await approve
        return status

    assert asyncio.run(run()) == pending.APPROVED and item.result == {"content": [], "done": True}
    stuck = store.create(caller_session_id="s", caller_tmux="c2", target_session_id="t", target_tmux="t",
                         action="a", args_summary="x", execute=None)
    stuck.status = pending.APPROVED
    assert asyncio.run(pending.wait_for(stuck, 0.2)) == pending.APPROVED and stuck.result is None


def test_resolved_again_refuses_unless_epochs_match(env):
    _, mgr, _, _ = env
    view = SimpleNamespace(state=SimpleNamespace(session_manager=mgr))
    target = mgr.infos[1].session

    async def check(known, now):
        target.tmux_created_epoch = now
        return await write_tools._resolved_again(view, "ses_b", known)

    assert asyncio.run(check(None, None)).session.id == "ses_b"
    assert asyncio.run(check(5, 5)).session.id == "ses_b"
    for known, now in ((5, None), (5, 6), (None, 6)):
        with pytest.raises(write_tools.ToolError):
            asyncio.run(check(known, now))
