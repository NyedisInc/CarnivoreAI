
from __future__ import annotations

from contextlib import closing

import sqlite3
from pathlib import Path

import pytest

from src.cplugs.host import capabilities, session_actions
from src.cplugs.huddle import held
from src.cplugs.huddle.nudge import pick as nudge_pick, planning, scheduler as nudge_scheduler
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.ladder import MIGRATIONS, SCHEMA_VERSION
from src.core.work.storage import WorkStorage
from tests.python.cplugs.huddle.test_task_manager_nudge_sweep import ITEMS, LISTS, Rig, rig  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note, row  # noqa: F401

SESSIONS = "/api/v1/cplugs/huddle/sessions"
UUID_A, UUID_B = "7f3e1c00-0000-4000-8000-00000000000a", "7f3e1c00-0000-4000-8000-00000000000b"


def sess(client, key: str, on):
    return client.put(f"{SESSIONS}/{key}/prefs", json={"nudge": on})


def test_rung_28_adds_session_prefs_to_a_rung_27_file(tmp_path: Path):
    path = tmp_path / "huddle.db"
    with sqlite3.connect(path) as conn:
        for step in MIGRATIONS[:27]:
            conn.executescript(step)
        conn.execute("INSERT INTO list_prefs (list_key, nudge, updated_at) VALUES ('12', 1, 1)")
        conn.execute("PRAGMA user_version = 27")
    TaskManagerStore(WorkStorage(path.parent), notify=lambda t: None).list_items("12")
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        info = {r[1]: r for r in conn.execute("PRAGMA table_info(session_prefs)")}
        assert list(info) == ["session_uuid", "nudge", "updated_at", "dnd"] and info["session_uuid"][5] == 1 and info["nudge"][3] == 0
        assert conn.execute("SELECT nudge FROM list_prefs WHERE list_key = '12'").fetchone()[0] == 1


@pytest.mark.parametrize("own,project,expected", [(None, True, True), (None, False, False), (True, False, True), (False, True, False),
                                                  (True, True, True), (False, False, False)])
def test_a_session_follows_its_project_unless_its_own_switch_is_set(own, project, expected):
    assert planning.effective(own, project) is expected


def test_session_prefs_routes_store_validate_clear_and_are_authenticated(client, app, rig):
    assert sess(client, UUID_A, True).json() == {"session": UUID_A, "nudge": True}
    assert client.get(f"{SESSIONS}/{UUID_A}/prefs").json() == {"session": UUID_A, "nudge": True}
    rig.switch(client)
    assert client.get("/api/v1/cplugs/huddle/session-prefs").json() == {"sessions": {UUID_A: True}, "lists": {"12": True}, "leads": {}, "dnd": []}
    assert sess(client, UUID_A, False).json()["nudge"] is False and rig.nudge_store.session_prefs() == {UUID_A: False}
    assert sess(client, UUID_A, None).json()["nudge"] is None
    assert rig.nudge_store.session_prefs() == {} and client.get(f"{SESSIONS}/{UUID_A}/prefs").json()["nudge"] is None
    assert client.put(f"{SESSIONS}/{UUID_A}/prefs", json={}).status_code == 422
    assert client.put(f"{SESSIONS}/{UUID_A}/prefs", json={"nudge": "yes"}).status_code == 422
    assert sess(client, "bad key!", True).status_code in (400, 404) and sess(client, "x" * 101, True).status_code == 400
    app.dependency_overrides.clear()
    from fastapi.testclient import TestClient
    with TestClient(app) as anonymous:
        assert anonymous.get(f"{SESSIONS}/{UUID_A}/prefs").status_code in (401, 403)
        assert anonymous.put(f"{SESSIONS}/{UUID_A}/prefs", json={"nudge": True}).status_code in (401, 403)
        assert anonymous.get("/api/v1/cplugs/huddle/session-prefs").status_code in (401, 403)


def test_a_session_switch_alone_arms_the_scheduler_and_sweeps_its_project(client, rig):
    async def scenario():
        import asyncio
        scheduler = nudge_scheduler.Scheduler(rig.nudge_ctx, clock=lambda: rig.later(0))
        assert await asyncio.to_thread(scheduler._timeout) is None
        await asyncio.to_thread(rig.nudge_store.set_session_pref, "ses_new", True)
        assert await asyncio.to_thread(scheduler._timeout) is not None and rig.nudge_store.nudge_lists() == []
        await asyncio.to_thread(rig.nudge_store.set_session_pref, "ses_new", None)
        scheduler._next_sweep = 0.0
        assert await asyncio.to_thread(scheduler._timeout) is None

    import asyncio
    asyncio.run(scenario())
    item = rig.add(client)
    rig.nudge_store.set_session_pref("ses_new", True)
    rig.sweep(1.5)
    assert [t for t, _ in rig.pasted] == ["ses_new"] and rig.item(item["id"])["nudge"]["count"] == 1


def test_an_explicit_session_off_overrides_the_project_on(client, rig):
    item = rig.add(client)
    rig.switch(client)
    rig.nudge_store.set_session_pref("ses_new", False)
    rig.nudge_store.set_session_pref("ses_old", False)
    rig.sweep(1.5)
    assert rig.pasted == [] and "nudge" not in rig.item(item["id"])
    rig.nudge_store.set_session_pref("ses_old", None)
    rig.sweep(1.6)
    assert [t for t, _ in rig.pasted] == ["ses_old"]


def test_an_idle_session_with_no_claim_is_told_to_pick_up_the_top_open_item(client, rig):
    rig.set_rows([rig.fresh("ses_new", idle_hours=2.0)])
    parked = rig.add(client, text="parked")
    client.patch(f"{ITEMS}/{parked['id']}", json={"state": "todo"})
    asked = rig.add(client, text="asks")
    rig.store.post(asked["id"], "which?", actor="claude", kind="question")
    waiting = rig.add(client, text="waits")
    client.patch(f"{ITEMS}/{waiting['id']}", json={"kind": "waiting"})
    installing = rig.add(client, text="installs")
    client.patch(f"{ITEMS}/{installing['id']}", json={"state": "waiting"})
    taken = rig.add(client, text="taken")
    rig.store.mark_working(taken["id"], "someone-else")
    first, second = rig.add(client, text="first open"), rig.add(client, text="second open")
    rig.switch(client)
    rig.sweep(0.5)
    assert len(rig.pasted) == 1
    text = rig.pasted[0][1]
    assert text.startswith("huddle nudge: you have been idle for ") and 'Pick up the next open item, "first open"' in text
    assert "second open" not in text and "parked" not in text and "taken" not in text
    assert rig.item(first["id"])["nudge"]["count"] == 1 and "nudge" not in rig.item(second["id"])
    rig.sweep(0.6)
    assert len(rig.pasted) == 1


def test_a_session_holding_a_claim_is_not_asked_to_pick_up_another(client, rig):
    rig.set_rows([rig.fresh("ses_new", idle_hours=2.0)])
    mine = rig.add(client, text="mine")
    rig.store.mark_working(mine["id"], "ses_new")
    rig.add(client, text="next")
    rig.switch(client)
    rig.sweep(0.5)
    assert rig.pasted == []


def test_an_empty_list_or_one_with_nothing_eligible_sends_nothing(client, rig):
    rig.set_rows([rig.fresh("ses_new", idle_hours=2.0)])
    rig.switch(client)
    rig.sweep(3.0)
    assert rig.pasted == []
    asked = rig.add(client, text="asks")
    rig.store.post(asked["id"], "which?", actor="claude", kind="question")
    rig.sweep(3.0)
    assert rig.pasted == []


def test_an_unclaimed_item_goes_to_an_idle_session_never_the_busy_swarm_user(client, rig):
    rig.set_rows([rig.fresh("ses_new", state="working"), rig.fresh("ses_old", idle_hours=0.1)])
    item = rig.add(client)
    rig.switch(client)
    rig.sweep(1.5)
    assert [t for t, _ in rig.pasted] == ["ses_old"]
    assert "unclaimed" in rig.pasted[0][1] and rig.item(item["id"])["nudge"]["count"] == 1


def test_the_idle_session_that_last_used_the_swarm_wins(client, rig):
    rig.set_rows([rig.fresh("ses_new", idle_hours=0.2), rig.fresh("ses_old", idle_hours=0.1)])
    rig.add(client)
    rig.switch(client)
    rig.sweep(1.5)
    assert [t for t, _ in rig.pasted] == ["ses_new"]


def test_with_no_swarm_user_the_most_recently_active_idle_session_wins(client, rig):
    rig.set_rows([rig.fresh("ses_a1", idle_hours=0.2), rig.fresh("ses_a2", idle_hours=0.1)])
    item = rig.add(client)
    rig.switch(client)
    rig.sweep(1.5)
    assert [t for t, _ in rig.pasted] == ["ses_a2"] and rig.item(item["id"])["nudge"]["count"] == 1


def test_one_item_per_nudge_even_when_several_are_due(client, rig):
    first, second, third = rig.add(client, text="one"), rig.add(client, text="two"), rig.add(client, text="three")
    rig.switch(client)
    rig.sweep(1.5)
    assert len(rig.pasted) == 1 and '"one"' in rig.pasted[0][1] and "two" not in rig.pasted[0][1] and "three" not in rig.pasted[0][1]
    assert "nudge" not in rig.item(second["id"]) and "nudge" not in rig.item(third["id"]) and rig.item(first["id"])["nudge"]["count"] == 1


def test_a_stalled_item_stops_blocking_and_the_next_one_is_offered(client, rig):
    first, second = rig.add(client, text="stuck"), rig.add(client, text="next")
    rig.own(first["id"])
    rig.switch(client)
    for hours in (1.1, 3.2, 6.3):
        rig.sweep(hours)
    before = len(rig.pasted)
    rig.sweep(10.5)
    assert rig.item(first["id"])["nudge"]["stalled"] is True and rig.item(first["id"])["needs_action"] == "answer"
    assert len(rig.pasted) == before + 1 and '"next"' in rig.pasted[-1][1]
    assert all('"stuck"' not in text for _target, text in rig.pasted[before:])


def test_a_busy_only_project_wakes_nobody_and_an_asleep_one_is_woken_only_with_no_live_session(client, rig, monkeypatch):
    rig.set_rows([rig.fresh("ses_new", state="working")])
    item = rig.add(client)
    rig.switch(client)

    async def asleep():
        return [{"session_uuid": "uuid-1", "project_id": 12, "name": "carnivore"}]

    async def wake(request, uuid):
        rig.woke.append(uuid)
        woken = rig.fresh("ses_woken")
        woken.session_row_id = 5
        rig.set_rows([woken])
        return {"status": "started", "detail": None, "code": None}

    monkeypatch.setattr(session_actions, "asleep", lambda request: asleep())
    monkeypatch.setattr(session_actions, "wake", wake)
    monkeypatch.setattr(session_actions, "start", lambda request, pid: pytest.fail("a nudge never starts a session"))
    monkeypatch.setattr(capabilities, "session_uuids", lambda ids: {5: "uuid-1"})
    rig.sweep(1.5)
    assert rig.woke == [] and rig.pasted == []
    rig.set_rows([])
    rig.sweep(1.6)
    assert rig.woke == ["uuid-1"] and [t for t, _ in rig.pasted] == ["ses_woken"] and rig.item(item["id"])["nudge"]["count"] == 1


def test_a_held_list_and_joes_turn_items_are_still_never_nudged(client, rig):
    from fastapi import HTTPException
    import asyncio
    from src.cplugs.huddle.nudge import sweep as nudge_sweep
    rig.set_rows([rig.fresh("ses_new", idle_hours=3.0)])
    item = rig.add(client)
    outbox = client.post(f"{LISTS}/12/items", json={"text": "joe wrote"}).json()
    rig.switch(client)

    async def scenario():
        held.hold(rig.ctx, "12", "ses_new", "label", HTTPException(status_code=409, detail={"code": "pane_dialog_open"}), lambda: asyncio.sleep(0))
        try:
            await nudge_sweep.sweep(rig.nudge_ctx, lambda: rig.later(1.5))
            assert [h["list"] for h in held.snapshot()] == ["12"]
        finally:
            held.reset()

    asyncio.run(scenario())
    assert rig.pasted == [] and "nudge" not in rig.item(item["id"])
    assert rig.store.item(outbox["id"])["status"] == "waiting_to_send"


def test_pure_pickup_helpers():
    assert nudge_pick.last_activity_epoch(None) is None and nudge_pick.last_activity_epoch("junk") is None
    assert nudge_pick.last_activity_epoch("1970-01-01T00:01:00") == 60.0
    assert nudge_pick.last_activity_epoch("1970-01-01T00:01:00+00:00") == 60.0


def test_a_waiting_install_item_is_never_nudged(client, rig):
    rig.set_rows([rig.fresh("ses_new", idle_hours=2.0)])
    item = rig.add(client, text="ship it")
    rig.own(item["id"])
    client.patch(f"{ITEMS}/{item['id']}", json={"state": "waiting"})
    with closing(rig.store._connect(True)) as conn, conn:
        conn.execute("UPDATE work_items SET claude_read_seq = joe_seq WHERE id = ?", (item["id"],))
    rig.switch(client)
    for hours in (0.5, 1.5, 5.0, 30.0):
        rig.sweep(hours)
    assert rig.pasted == [] and "nudge" not in rig.item(item["id"])
