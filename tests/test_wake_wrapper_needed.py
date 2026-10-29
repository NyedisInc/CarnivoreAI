
from __future__ import annotations

import pytest

from tests.test_session_sleep import (  # noqa: F401
    NAME,
    ROW_UUID,
    _insert,
    _presence,
    _row,
    client,
    state_dir,
)

# ruff: noqa: E402
from src.api import recreate_routes, session_sleep_routes
from src.core import session_sleep
from src.core.session_recreate_presence import TMUX_PRESENT
from src.core.session_restore_offer import NEVER_OFFERED
from src.core.session_wake_choice import recorded_wake_agent

IDS = ["claude-skip-permissions", "keyc", "clxor", "cldl", "claude-chrome"]


def _ids(monkeypatch, ids):
    monkeypatch.setattr("src.core.session_agent_choice.configured_wrapper_ids",
                        lambda settings_obj: ids)


def _recorder(monkeypatch):
    called = []

    async def _recreate(session_uuid, agent_type, *, get_manager, row_overrides=None):
        called.append((session_uuid, agent_type))
        return recreate_routes.RecreateResponse(
            status="started", session_uuid=session_uuid, session_name=NAME,
            presence="gone", conversation="resumed", detail="resumed",
        )

    monkeypatch.setattr("src.api.recreate_action.recreate_by_uuid", _recreate)
    return called


def _set_source(state_dir, source):
    from src.core.db import connect, db_path_for

    with connect(db_path_for(state_dir), create=False) as conn:
        conn.execute("UPDATE sessions SET agent_family_source = ? WHERE session_uuid = ?",
                     (source, ROW_UUID))




@pytest.mark.parametrize("row, ids, expected", [
    ({"agent_type": "claude", "agent_family_source": "launched"}, IDS, None),
    ({"agent_type": "keyc", "agent_family_source": "inferred_process"}, IDS, None),
    ({"agent_type": "", "agent_family_source": "not_launched"}, IDS, None),
    ({"agent_type": "keyc", "agent_family_source": "launched"}, IDS, "keyc"),
    ({"agent_type": "keyc", "agent_family_source": "not_launched"}, IDS, "keyc"),
    ({"agent_type": "claude", "agent_family_source": "launched"}, None, "claude"),
])
def test_recorded_wake_agent(row, ids, expected):
    assert recorded_wake_agent(row, ids) == expected




def test_a_family_name_row_asks_for_a_wrapper_instead_of_failing(state_dir, client, monkeypatch):
    c, _ = client
    _insert(state_dir, lifecycle="stopped", source="slept_by_user", agent_type="claude")
    _set_source(state_dir, "launched")
    _ids(monkeypatch, IDS)
    called = _recorder(monkeypatch)
    r = c.post(f"/api/v1/sessions/{ROW_UUID}/wake")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "refused"
    assert body["code"] == "wrapper_needed"
    assert body["wrapper_options"] == IDS
    assert "'claude' is not a configured launch wrapper" in body["detail"]
    assert called == [], "nothing may be launched on a value that is not a wrapper"
    assert session_sleep.is_asleep(_row(state_dir)), "the row stays asleep"


def test_an_inferred_wrapper_is_not_launched_unasked(state_dir, client, monkeypatch):
    c, _ = client
    _insert(state_dir, lifecycle="stopped", source="slept_by_user", agent_type="keyc")
    _set_source(state_dir, "inferred_process")
    _ids(monkeypatch, IDS)
    called = _recorder(monkeypatch)
    body = c.post(f"/api/v1/sessions/{ROW_UUID}/wake").json()
    assert body["code"] == "wrapper_needed"
    assert "inferred" in body["detail"]
    assert called == []


def test_the_pick_comes_back_through_wake_as_the_choice(state_dir, client, monkeypatch):
    c, _ = client
    _insert(state_dir, lifecycle="stopped", source="slept_by_timer", agent_type="claude")
    _ids(monkeypatch, IDS)
    called = _recorder(monkeypatch)
    r = c.post(f"/api/v1/sessions/{ROW_UUID}/wake",
               json={"agent_type": "claude-skip-permissions"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "started"
    assert r.json()["code"] is None
    assert called == [(ROW_UUID, "claude-skip-permissions")]


def test_a_configured_recorded_wrapper_wakes_without_asking(state_dir, client, monkeypatch):
    c, _ = client
    _insert(state_dir, lifecycle="stopped", source="slept_by_user", agent_type="keyc")
    _set_source(state_dir, "launched")
    _ids(monkeypatch, IDS)
    called = _recorder(monkeypatch)
    assert c.post(f"/api/v1/sessions/{ROW_UUID}/wake").json()["status"] == "started"
    assert called == [(ROW_UUID, "keyc")]


def test_a_row_with_no_recorded_wrapper_asks_rather_than_409(state_dir, client, monkeypatch):
    c, _ = client
    _insert(state_dir, lifecycle="stopped", source="slept_by_user", agent_type=None)
    _ids(monkeypatch, IDS)
    called = _recorder(monkeypatch)
    r = c.post(f"/api/v1/sessions/{ROW_UUID}/wake")
    assert r.status_code == 200, r.text
    assert r.json()["code"] == "wrapper_needed"
    assert called == []


def test_a_row_that_is_not_asleep_still_refuses_even_with_a_pick(state_dir, client, monkeypatch):
    c, _ = client
    _insert(state_dir, lifecycle="stopped", source="closed_by_user", agent_type="keyc")
    called = _recorder(monkeypatch)
    r = c.post(f"/api/v1/sessions/{ROW_UUID}/wake", json={"agent_type": "keyc"})
    assert r.status_code == 409
    assert called == []




def test_auto_sleep_marks_the_row_slept_by_timer(state_dir, client, monkeypatch):
    c, closes = client
    _insert(state_dir, lifecycle="running", source="tmux_list")
    _presence(monkeypatch, TMUX_PRESENT, "gone")
    app_state = c.app.state
    import asyncio

    result = asyncio.run(session_sleep_routes.auto_sleep_by_uuid(app_state, ROW_UUID))
    assert result.status == "asleep", result.detail
    row = _row(state_dir)
    assert row["lifecycle_source"] == "slept_by_timer"
    assert session_sleep.is_asleep(row)
    listed = c.get("/api/v1/sessions/asleep").json()
    assert [r["session_uuid"] for r in listed] == [ROW_UUID]


def test_the_user_route_still_writes_slept_by_user(state_dir, client, monkeypatch):
    c, _ = client
    _insert(state_dir, lifecycle="running", source="tmux_list")
    _presence(monkeypatch, TMUX_PRESENT, "gone")
    assert c.post(f"/api/v1/sessions/{ROW_UUID}/sleep").json()["status"] == "asleep"
    assert _row(state_dir)["lifecycle_source"] == "slept_by_user"


def test_a_timer_sleep_is_never_offered_for_reopen():
    assert "slept_by_timer" in NEVER_OFFERED
    assert "slept_by_user" in NEVER_OFFERED


def test_mark_asleep_refuses_a_source_no_reader_knows(state_dir):
    from src.core.db import connect, db_path_for

    row_id = _insert(state_dir)
    with connect(db_path_for(state_dir), create=False) as conn:
        with pytest.raises(ValueError):
            session_sleep.mark_asleep(conn, row_id=row_id, tmux_name=NAME,
                                      tmux_created_epoch=1790090835, source="asleep")
