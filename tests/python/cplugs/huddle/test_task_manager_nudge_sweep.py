
from __future__ import annotations

import asyncio
from contextlib import closing
import sqlite3
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import one_shot_routes
from src.cplugs.host import capabilities, runtime, session_actions, state as owner_state
from dataclasses import replace as _replace

from src.cplugs.huddle import held, schedule, service
from src.cplugs.huddle.nudge import planning, scheduler as nudge_scheduler, settings as nudge_settings, sweep as nudge_sweep
from src.cplugs.huddle.nudge_store import NudgeStore
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.ladder import MIGRATIONS, SCHEMA_VERSION
from src.core.work.storage import WorkStorage
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note, row  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import Env

LISTS = "/api/v1/cplugs/huddle/lists"
ITEMS = "/api/v1/cplugs/huddle/items"
HOUR = 3600.0


def enable_nudge(host) -> None:
    d = runtime.find("huddle")
    owner_state.update(host.state_dir, d.manifest, None, lambda st: _replace(st, settings={**st.settings, nudge_settings.ENABLED: True}))


class Rig(Env):

    def __init__(self, app, monkeypatch) -> None:
        super().__init__(app, monkeypatch)
        self.toasts: list = []
        enable_nudge(self.host)
        self.nudge_ctx = self.ctx
        self.nudge_ctx.toast = lambda session_id, title: self.toasts.append((session_id, title))
        self.base = time.time()
        self.nudge_store = NudgeStore(self.store)
        self.set_rows([self.fresh("ses_new"), self.fresh("ses_old"), row("ses_other", 99)])

    def fresh(self, sid: str, project: int = 12, state: str = "idle", idle_hours: float = 0.0):
        made = row(sid, project)
        made.activity_status = state
        made.session.last_activity = datetime.fromtimestamp(self.base - idle_hours * HOUR, tz=timezone.utc).replace(tzinfo=None)
        return made

    def add(self, client, list_key="12", text="check the build") -> dict:
        return self.store.add(list_key, text, actor="claude")

    def later(self, hours: float) -> float:
        return self.base + hours * HOUR

    def switch(self, client, on: bool = True, key: str = "12"):
        return client.put(f"{LISTS}/{key}/prefs", json={"nudge": on})

    def sweep(self, hours: float):
        return asyncio.run(nudge_sweep.sweep(self.nudge_ctx, lambda: self.later(hours)))

    def item(self, item_id: int) -> dict:
        return self.store.item(item_id)

    def own(self, item_id: int, key: str = "ses_new") -> None:
        with closing(self.store._connect(True)) as conn, conn:
            conn.execute("UPDATE work_items SET owner_session_key = ? WHERE id = ?", (key, item_id))

    def nudge_lines(self, item_id: int) -> list:
        return [m for m in self.item(item_id)["thread"] if m["author_key"] == "nudge"]


@pytest.fixture
def rig(app, monkeypatch):
    r = Rig(app, monkeypatch)
    note(app, "ses_new", "12", 100.0)
    yield r
    held.reset()
    schedule.stop()


def test_rung_27_adds_the_two_tables_to_a_rung_26_file(tmp_path: Path):
    path = tmp_path / "huddle.db"
    with sqlite3.connect(path) as conn:
        for step in MIGRATIONS[:26]:
            conn.executescript(step)
        conn.execute("INSERT INTO items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, seq) "
                     "VALUES ('12', 'old', 0, 'joe', 'open', 1, 1, 1, 1)")
        conn.execute("PRAGMA user_version = 26")
    items = TaskManagerStore(WorkStorage(path.parent), notify=lambda t: None).list_items("12")["items"]
    assert "nudge" not in items[0]
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert [r[1] for r in conn.execute("PRAGMA table_info(list_prefs)")] == ["list_key", "nudge", "updated_at", "inbox"]
        assert [r[1] for r in conn.execute("PRAGMA table_info(item_nudges)")] == ["item_id", "count", "last_at", "basis", "stalled_at"]


def test_prefs_routes_are_authenticated_validated_and_shown_on_the_lists(client, app, rig):
    assert rig.switch(client).json() == {"list": "12", "nudge": True}
    assert client.get(f"{LISTS}/12/prefs").json() == {"list": "12", "nudge": True}
    listed = {l["key"]: l["nudge"] for l in client.get(LISTS).json()["lists"]}
    assert listed == {"all": False, "12": True}
    assert rig.switch(client, key="all").status_code == 400
    assert client.get(f"{LISTS}/all/prefs").json() == {"list": "all", "nudge": False}
    assert rig.switch(client, key="77").status_code == 404
    assert client.put(f"{LISTS}/12/prefs", json={}).status_code == 422 and client.put(f"{LISTS}/12/prefs", json={"nudge": "yes"}).status_code == 422
    assert rig.switch(client, False).json()["nudge"] is False and rig.nudge_store.nudge_lists() == []
    app.dependency_overrides.clear()
    from fastapi.testclient import TestClient
    with TestClient(app) as anonymous:
        assert anonymous.get(f"{LISTS}/12/prefs").status_code in (401, 403)
        assert anonymous.put(f"{LISTS}/12/prefs", json={"nudge": True}).status_code in (401, 403)


def test_an_idle_open_item_is_nudged_once_with_a_born_read_thread_line(client, rig):
    item = rig.add(client)
    rig.switch(client)
    before = rig.item(item["id"])
    rig.sweep(0.5)
    assert rig.pasted == []
    rig.sweep(1.2)
    assert len(rig.pasted) == 1
    target, text = rig.pasted[0]
    assert target == "ses_new" and text.startswith("huddle nudge: ") and "unclaimed" in text and "check the build" in text and "task_manager_changes" in text
    after = rig.item(item["id"])
    assert after["nudge"]["count"] == 1 and after["nudge"]["stalled"] is False
    (line,) = rig.nudge_lines(item["id"])
    assert line["text"] == "nudged 1 of 3" and line["unread"] is False and line["kind"] == "info" and line["category"] == "nudge"
    for field in ("status", "unread", "info_unread", "attention_unread", "revision", "state"):
        assert after[field] == before[field], field
    assert after["seq"] > before["seq"]
    rig.sweep(1.3)
    assert len(rig.pasted) == 1


def test_back_off_then_an_owned_task_stalls_into_one_question_and_no_toast(client, rig):
    item = rig.add(client)
    rig.own(item["id"])
    rig.switch(client)
    for hours in (1.1, 3.2, 6.3):
        rig.sweep(hours)
    assert len(rig.pasted) == 3 and rig.item(item["id"])["nudge"]["count"] == 3
    rig.sweep(7.0)
    assert len(rig.pasted) == 3 and rig.item(item["id"])["status"] != "question"
    rig.sweep(10.5)
    asked = rig.item(item["id"])
    assert asked["status"] == "question" and asked["needs_action"] == "answer" and asked["nudge"]["stalled"] is True
    question = [m for m in asked["thread"] if m["kind"] == "question"][-1]
    assert question["author_key"] == "carnivore" and question["category"] == "stall" and not question["answered"]
    assert len(rig.pasted) == 3 and rig.toasts == []
    rig.sweep(20.0)
    assert len([m for m in rig.item(item["id"])["thread"] if m["kind"] == "question"]) == 1 and len(rig.pasted) == 3


def test_any_write_resets_the_count_and_the_stall(client, rig):
    item = rig.add(client)
    rig.switch(client)
    rig.sweep(1.1)
    assert rig.item(item["id"])["nudge"]["count"] == 1
    client.post(f"{ITEMS}/{item['id']}/messages", json={"text": "status?"})
    assert "nudge" not in rig.item(item["id"])
    assert rig.item(item["id"])["status"] == "waiting_to_send"


def test_active_held_blocked_and_joes_turn_items_are_skipped(client, rig):
    item = rig.add(client, text="a")
    asked = rig.add(client, text="b")
    rig.store.post(asked["id"], "which one?", actor="claude", kind="question")
    review = rig.add(client, text="c")
    client.patch(f"{ITEMS}/{review['id']}", json={"state": "review"})
    parked = rig.add(client, text="d")
    client.patch(f"{ITEMS}/{parked['id']}", json={"state": "todo"})
    waiting = rig.add(client, text="e")
    client.patch(f"{ITEMS}/{waiting['id']}", json={"kind": "waiting"})
    rig.switch(client)
    rig.sweep(1.5)
    assert len(rig.pasted) == 1
    text = rig.pasted[0][1]
    assert '"a"' in text and all(f'"{w}"' not in text for w in "bcde")
    for skipped in (asked, review, parked, waiting):
        assert rig.nudge_lines(skipped["id"]) == []


def test_a_busy_or_prompting_session_is_skipped_and_nothing_is_counted(client, rig):
    item = rig.add(client)
    rig.switch(client)
    for state in ("working", "question", "notice"):
        busy = row("ses_new", 12)
        busy.activity_status = state
        rig.set_rows([busy])
        rig.sweep(1.5)
        assert rig.pasted == [] and "nudge" not in rig.item(item["id"]), state


def test_a_refused_paste_is_not_counted_and_never_held(client, rig, monkeypatch):
    item = rig.add(client)
    rig.switch(client)

    async def refuse(request, session_id, text):
        raise HTTPException(status_code=409, detail={"code": "pane_dialog_open", "detail": "a dialog is open"})

    monkeypatch.setattr(one_shot_routes, "paste_through_gates", refuse)
    rig.sweep(1.5)
    assert "nudge" not in rig.item(item["id"]) and held.snapshot() == [] and rig.nudge_lines(item["id"]) == []


def test_a_list_with_a_held_tell_is_skipped_so_the_hold_survives(client, rig):
    item = rig.add(client)
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


def test_a_nudge_carries_joes_untold_changes_by_the_one_tell_path(client, rig):
    rig.add(client)
    joes = client.post(f"{LISTS}/12/items", json={"text": "joe wrote this later"}).json()
    assert rig.store.item(joes["id"])["status"] == "waiting_to_send"
    rig.switch(client)
    rig.sweep(1.5)
    assert len(rig.pasted) == 1 and "joe wrote this later" not in rig.pasted[0][1]
    assert "task_manager_changes" in rig.pasted[0][1] and "list 12" in rig.pasted[0][1]
    assert rig.store.item(joes["id"])["status"] == "open"
    assert rig.nudge_lines(joes["id"]) == []


def test_a_project_with_no_live_session_wakes_the_newest_asleep_one_and_never_starts_one(client, rig, monkeypatch):
    rig.set_rows([row("ses_other", 99)])
    item = rig.add(client)
    rig.switch(client)

    async def asleep():
        return [{"session_uuid": "uuid-1", "project_id": 12, "name": "carnivore"}]

    async def wake(request, uuid):
        rig.woke.append(uuid)
        woken = row("ses_woken", 12)
        woken.session_row_id = 5
        rig.set_rows([row("ses_other", 99), woken])
        return {"status": "started", "detail": None, "code": None}

    monkeypatch.setattr(session_actions, "asleep", lambda request: asleep())
    monkeypatch.setattr(session_actions, "wake", wake)
    monkeypatch.setattr(session_actions, "start", lambda request, pid: pytest.fail("a nudge never starts a session"))
    monkeypatch.setattr(capabilities, "session_uuids", lambda ids: {5: "uuid-1"})
    rig.sweep(1.5)
    assert rig.woke == ["uuid-1"] and [t for t, _ in rig.pasted] == ["ses_woken"]
    assert rig.item(item["id"])["nudge"]["count"] == 1


def test_no_session_and_nothing_asleep_does_nothing(client, rig, monkeypatch):
    rig.set_rows([])
    item = rig.add(client)
    rig.switch(client)

    async def asleep():
        return []

    monkeypatch.setattr(session_actions, "asleep", lambda request: asleep())
    monkeypatch.setattr(session_actions, "start", lambda request, pid: pytest.fail("a nudge never starts a session"))
    rig.sweep(1.5)
    assert rig.pasted == [] and "nudge" not in rig.item(item["id"])


def test_a_changed_setting_is_read_by_the_next_sweep_without_a_restart(client, rig):
    rig.add(client)
    rig.switch(client)
    rig.sweep(1.5)
    assert len(rig.pasted) == 1
    other = rig.add(client, text="second")
    d = runtime.find("huddle")
    owner_state.update(rig.host.state_dir, d.manifest, None, lambda st: replace(st, settings={**st.settings, "nudgeMinutes": 1440}))
    assert rig.nudge_ctx.settings_now()["nudgeMinutes"] == 1440 and rig.nudge_ctx.settings["nudgeMinutes"] == 60
    rig.sweep(8.0)
    assert len(rig.pasted) == 1 and "nudge" not in rig.item(other["id"])


def test_the_scheduler_arms_the_sweep_only_while_a_list_has_the_nudge_on(client, rig):
    async def scenario():
        scheduler = nudge_scheduler.Scheduler(rig.nudge_ctx, clock=lambda: rig.later(0))
        assert await asyncio.to_thread(scheduler._timeout) is None
        rig.nudge_store.set_pref("12", True)
        timeout = await asyncio.to_thread(scheduler._timeout)
        assert timeout is not None and timeout <= nudge_scheduler.MAX_SLEEP_S
        assert await scheduler.due() is True and scheduler._next_sweep == pytest.approx(rig.later(0) + 300.0)
        assert await scheduler.due() is False
        rig.nudge_store.set_pref("12", False)
        scheduler._next_sweep = 0.0
        assert await scheduler.due() is False and await asyncio.to_thread(scheduler._timeout) is None

    asyncio.run(scenario())


def test_a_prefs_write_re_arms_the_sleeping_scheduler(client, rig):
    async def scenario():
        nudge_scheduler.start(rig.nudge_ctx)
        try:
            scheduler = nudge_scheduler.Running.scheduler
            await asyncio.sleep(0.05)
            poked = asyncio.Event()
            scheduler.poke = poked.set
            await asyncio.to_thread(rig.nudge_store.set_pref, "12", True)
            await asyncio.wait_for(poked.wait(), 1.0)
        finally:
            nudge_scheduler.stop()

    asyncio.run(scenario())


def test_the_nudge_switch_off_means_the_sweep_has_nothing_to_do(client, rig):
    rig.add(client)
    rig.switch(client)
    d = runtime.find("huddle")
    owner_state.update(rig.host.state_dir, d.manifest, None, lambda st: replace(st, settings={**st.settings, nudge_settings.ENABLED: False}))
    assert rig.sweep(1.5) == nudge_settings.default(nudge_settings.MINUTES)

    async def scenario():
        scheduler = nudge_scheduler.Scheduler(rig.nudge_ctx, clock=lambda: rig.later(1.5))
        assert await scheduler.due() is False and await asyncio.to_thread(scheduler._timeout) is None

    asyncio.run(scenario())
    assert rig.pasted == []


def test_a_scheduled_fire_skips_an_item_that_is_waiting_on_joe(client, rig):
    from datetime import datetime, timedelta, timezone
    asked = rig.add(client, text="needs an answer")
    plain = rig.add(client, text="plain")
    for item in (asked, plain):
        client.patch(f"{ITEMS}/{item['id']}", json={"fire_at": (datetime.now(timezone.utc) + timedelta(seconds=60)).astimezone().isoformat()})
    rig.store.post(asked["id"], "which?", actor="claude", kind="question")
    for item in (asked, plain):
        rig.overdue(item["id"])
    claimed = rig.store.claim_due_triggers()
    assert [c["id"] for c in claimed] == [plain["id"]]
    assert "waiting on you" in rig.store.item(asked["id"])["start_trigger"]["last_error"]
