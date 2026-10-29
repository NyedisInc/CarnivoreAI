
from __future__ import annotations

import json
from contextlib import closing

from src.core.crosstalk import store as crosstalk_store
from src.core.db import connect, db_path_for
from src.core.mcp import pending
from src.models import Session, SessionInfo
from src.api.recreate_routes import RecreateResponse
from tests.python.mcp.test_mcp_endpoint import _call
from tests.python.mcp.test_mcp_write import env  # noqa: F401


def _text(result) -> str:
    return result["content"][0]["text"]


def _seed_asleep(state_dir) -> None:
    with closing(connect(db_path_for(state_dir), create=False)) as conn:
        conn.execute(
            "INSERT INTO sessions (id, session_uuid, tmux_name, tmux_created_epoch, title, agent_type, origin, lifecycle, "
            "lifecycle_source, created_at, updated_at) VALUES (33, 'uuid-33', 'cloude_c', 100, 'Sleepy', 'claude', 'observed', "
            "'stopped', 'slept_by_user', '2026-10-03T00:00:00Z', '2026-10-03T00:00:00Z')")


def test_send_to_asleep_session_wakes_it_after_approval_then_delivers(env, monkeypatch, tmp_path):  # noqa: F811
    client, mgr, _, _ = env
    _seed_asleep(tmp_path)
    woken: list = []

    async def fake_wake(app_state, session_uuid, agent_type=None):
        woken.append(session_uuid)
        with closing(connect(db_path_for(tmp_path), create=False)) as conn:
            conn.execute("UPDATE sessions SET lifecycle='running', lifecycle_source='created' WHERE session_uuid=?", (session_uuid,))
        mgr.infos.append(SessionInfo(session=Session(id="ses_c", working_dir="/tmp/x", tmux_created_epoch=200),
                                     tmux_session="cloude_c", label="Sleepy", session_row_id=33))
        return type("R", (), {"status": "started", "detail": ""})()

    monkeypatch.setattr("src.api.session_sleep_routes.wake_by_uuid", fake_wake)
    found = json.loads(_text(_call(client, mgr, "agents_lookup", {"query": "sleepy"})))
    assert found["agents"][0]["status"] == "asleep" and found["agents"][0]["id"] == "uuid-33"

    held = json.loads(_text(_call(client, mgr, "crosstalk_send", {"to": "@Sleepy", "text": "quick question"})))
    assert held["status"] == "pending" and not woken
    assert client.post(f"/api/v1/agent-actions/{held['id']}/approve").status_code == 200
    receipt = json.loads(_text(pending.get_store().get(held["id"]).result))
    stored = crosstalk_store.get(receipt["id"])
    assert woken == ["uuid-33"]
    assert stored["text"] == "quick question" and stored["receiver_key"] == "uuid-33" and stored["receiver_epoch"] == 200


def test_refused_wake_sends_nothing(env, monkeypatch, tmp_path):  # noqa: F811
    client, mgr, _, _ = env
    _seed_asleep(tmp_path)

    async def refuse(app_state, session_uuid, agent_type=None):
        return type("R", (), {"status": "refused", "detail": "pick a wrapper"})()

    monkeypatch.setattr("src.api.session_sleep_routes.wake_by_uuid", refuse)
    held = json.loads(_text(_call(client, mgr, "crosstalk_send", {"to": "@Sleepy", "text": "hello"})))
    assert client.post(f"/api/v1/agent-actions/{held['id']}/approve").status_code == 200
    result = pending.get_store().get(held["id"]).result
    assert "nothing" in _text(result).lower() or "not sent" in _text(result).lower() or result.get("isError")
    assert crosstalk_store.messages_for("uuid-33") == []


def test_approved_pair_wakes_and_delivers_with_no_new_approval(env, monkeypatch, tmp_path):  # noqa: F811
    client, mgr, _, _ = env
    _seed_asleep(tmp_path)
    epochs = iter([200, 300])
    ran: list = []

    async def fake_recreate(session_uuid, agent_type, get_manager=None):
        ran.append(session_uuid)
        epoch = next(epochs)
        with closing(connect(db_path_for(tmp_path), create=False)) as conn:
            conn.execute("UPDATE sessions SET lifecycle='running', lifecycle_source='created', tmux_created_epoch=? "
                         "WHERE session_uuid=?", (epoch, session_uuid))
        mgr.infos.append(SessionInfo(session=Session(id="ses_c", working_dir="/tmp/x", tmux_created_epoch=epoch),
                                     tmux_session="cloude_c", label="Sleepy", session_row_id=33))
        return RecreateResponse(status="started", session_uuid=session_uuid, presence="gone", conversation="resumed")

    monkeypatch.setattr("src.api.recreate_action.recreate_by_uuid", fake_recreate)
    monkeypatch.setattr("src.core.session_agent_choice.configured_wrapper_ids", lambda settings: ["claude"])
    monkeypatch.setattr("src.api.session_sleep_routes.session_sleep.is_asleep", lambda row: row["lifecycle"] == "stopped")
    held = json.loads(_text(_call(client, mgr, "crosstalk_send", {"to": "@Sleepy", "text": "first"})))
    assert held["status"] == "pending"
    assert client.post(f"/api/v1/agent-actions/{held['id']}/approve").status_code == 200
    assert ran == ["uuid-33"]
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        conn.execute("UPDATE sessions SET lifecycle='stopped', lifecycle_source='slept_by_user' WHERE session_uuid='uuid-33'")
    mgr.infos[:] = [i for i in mgr.infos if i.tmux_session != "cloude_c"]

    second = json.loads(_text(_call(client, mgr, "crosstalk_send", {"to": "@Sleepy", "text": "second"})))
    assert second.get("status") != "pending", second
    assert ran == ["uuid-33", "uuid-33"]
    stored = crosstalk_store.get(second["id"])
    assert stored["text"] == "second" and stored["receiver_epoch"] == 300
