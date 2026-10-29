
from __future__ import annotations

import json
import re
from pathlib import Path

from src.api.auth import require_auth
from src.core.mcp import pending, tools
from src.core.mcp.approvals import call_context, persist, runtime as approval_runtime
from src.main import app
from src.models import Session
from tests.python.mcp.test_mcp_endpoint import _call, _hdr
from tests.python.mcp.test_mcp_write import _text, env  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]


def _store(path: Path) -> pending.PendingActions:
    store = pending.PendingActions(file=persist.ActionFile(path))
    store.set_runtime(lambda item: approval_runtime.recheck(app, item), lambda item: approval_runtime.replay(app, item))
    return store


def _ask_stop(client, mgr) -> str:
    answer = json.loads(_text(_call(client, mgr, "session_stop", {"target": "cloude_b"})))
    assert answer["status"] == "pending"
    return answer["id"]


def test_a_pending_action_survives_a_restart_and_the_approve_replays_it(env, tmp_path):
    client, mgr, _, slept = env
    db = tmp_path / persist.FILE_NAME
    pending._store = _store(db)
    action_id = _ask_stop(client, mgr)
    assert db.stat().st_mode & 0o777 == 0o600
    pending._store = _store(db)
    row = pending.get_store().get(action_id)
    assert row is not None and row.status == pending.PENDING and row.execute is None and row.tool == "session_stop"
    assert [r["id"] for r in client.get("/api/v1/agent-actions").json()["items"]] == [action_id]
    approved = client.post(f"/api/v1/agent-actions/{action_id}/approve")
    assert approved.status_code == 200 and approved.json()["status"] == "approved", approved.text
    assert slept == ["uuid-22"]
    pending._store = _store(db)
    waited = _call(client, mgr, "approval_wait", {"id": action_id})
    assert "isError" not in waited and "asleep" in _text(waited)


def test_a_deny_is_final_across_a_restart(env, tmp_path):
    client, mgr, _, slept = env
    db = tmp_path / persist.FILE_NAME
    pending._store = _store(db)
    action_id = _ask_stop(client, mgr)
    pending._store = _store(db)
    assert client.post(f"/api/v1/agent-actions/{action_id}/deny").json()["status"] == "denied"
    pending._store = _store(db)
    assert client.post(f"/api/v1/agent-actions/{action_id}/approve").status_code == 409
    waited = _call(client, mgr, "approval_wait", {"id": action_id})
    assert waited["isError"] is True and "denied" in _text(waited) and not slept


def test_approve_time_recheck_refuses_a_different_tmux_instance(env, tmp_path):
    client, mgr, _, slept = env
    b = mgr.infos[1]
    mgr.infos[1] = b.model_copy(update={"session": Session(id="ses_b", working_dir="/tmp/x", tmux_created_epoch=100)})
    pending._store = _store(tmp_path / persist.FILE_NAME)
    action_id = _ask_stop(client, mgr)
    assert pending.get_store().get(action_id).target_epoch == 100
    mgr.infos[1] = b.model_copy(update={"session": Session(id="ses_b", working_dir="/tmp/x", tmux_created_epoch=200)})
    body = client.post(f"/api/v1/agent-actions/{action_id}/approve").json()
    assert body["status"] == "refused" and "different tmux instance" in body["reason"] and not slept
    waited = _call(client, mgr, "approval_wait", {"id": action_id})
    assert waited["isError"] is True and "refused when the owner approved" in _text(waited)


def test_a_replay_whose_target_is_gone_is_refused(env, tmp_path):
    client, mgr, _, slept = env
    db = tmp_path / persist.FILE_NAME
    pending._store = _store(db)
    action_id = _ask_stop(client, mgr)
    pending._store = _store(db)
    mgr.infos = mgr.infos[:1]
    body = client.post(f"/api/v1/agent-actions/{action_id}/approve").json()
    assert body["status"] == "refused" and body["reason"] and not slept


def test_a_replay_that_would_now_do_something_else_is_refused(env, tmp_path):
    client, mgr, _, _ = env
    db = tmp_path / persist.FILE_NAME
    pending._store = _store(db)
    answer = json.loads(_text(_call(client, mgr, "session_restart", {"target": "cloude_b"})))
    pending._store = _store(db)
    mgr.dead = True
    body = client.post(f"/api/v1/agent-actions/{answer['id']}/approve").json()
    assert body["status"] == "refused" and "changed since you were asked" in body["reason"]
    assert mgr.respawns == []


def test_the_per_caller_cap_holds_over_restored_items(env, tmp_path):
    client, mgr, _, _ = env
    db = tmp_path / persist.FILE_NAME
    pending._store = _store(db)
    for n in range(pending.MAX_PENDING_PER_CALLER):
        _call(client, mgr, "session_send_keys", {"target": "cloude_b", "text": f"echo {n}", "keys": ["Enter"]})
    pending._store = _store(db)
    assert pending.get_store().count_pending() == pending.MAX_PENDING_PER_CALLER
    body = _call(client, mgr, "session_send_keys", {"target": "cloude_b", "text": "one more"})
    assert body["isError"] is True and "already have 5" in _text(body)


def test_huddle_item_is_gone_from_every_schema_but_still_accepted(env):
    client, mgr, _, _ = env
    for definition in tools.tool_definitions():
        assert call_context.ARG not in definition["inputSchema"]["properties"], definition["name"]
    body = _call(client, mgr, "session_create", {"working_dir": "/tmp", "huddle_item": 215})
    assert json.loads(_text(body))["status"] == "pending"
    item = pending.get_store().list()[0]
    assert item["tool"] == "session_create" and "huddle_item" not in item["args"] and "huddle_item" not in item
    assert call_context.strip_legacy_arg("session_stop", {"target": "a", "huddle_item": 9}, tools.GATED_TOOLS) == {"target": "a"}
    assert call_context.strip_legacy_arg("sessions_list", {"huddle_item": 9}, tools.GATED_TOOLS) == {"huddle_item": 9}


def test_every_park_site_names_a_gated_tool():
    literal = re.compile(r"park\([^)]*?['\"]([a-z_]+)['\"](?!\s*[\]:])", re.S)
    found = set()
    for path in (ROOT / "src").rglob("*.py"):
        for match in literal.finditer(path.read_text()):
            found.add(match.group(1))
    known = call_context.GATED_TOOLS | set(call_context.ACTION_TOOLS)
    assert found and found - known == set(), sorted(found - known)


def test_only_the_owner_login_decides(env):
    client, mgr, _, slept = env
    action_id = _ask_stop(client, mgr)
    app.dependency_overrides.pop(require_auth, None)
    try:
        for headers in (_hdr(mgr), {"Authorization": "Bearer peer-token-not-a-login"}, {}):
            for verb in ("approve", "deny"):
                r = client.post(f"/api/v1/agent-actions/{action_id}/{verb}", headers=headers)
                assert r.status_code in (401, 403), (verb, headers, r.status_code)
    finally:
        app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
    assert pending.get_store().get(action_id).status == pending.PENDING and not slept


def test_no_tool_plugin_or_peer_path_can_decide():
    decide = re.compile(r"(?:store|get_store\(\))\.(approve|deny|execute_claimed|claim_for_beast|deny_for_caller)\(")
    allowed = {"src/api/agent_action_routes.py", "src/api/mcp_admin_routes.py", "src/core/mcp/beast_mode.py",
               "src/core/mcp/pending.py"}
    callers = {str(p.relative_to(ROOT)) for p in (ROOT / "src").rglob("*.py") if decide.search(p.read_text())}
    assert callers and callers <= allowed, sorted(callers - allowed)
    assert not (ROOT / "src/cplugs/sdk/approvals.py").exists()
