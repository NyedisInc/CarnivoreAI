
from __future__ import annotations

from contextlib import closing

import pytest

from src.cplugs.huddle import closure_undo, service
from src.cplugs.huddle.rules import TaskManagerForbidden
from tests.python.cplugs.huddle.test_task_manager_routes import app, client  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import ITEMS, env  # noqa: F401

BASE = "/api/v1/cplugs/huddle"
DAILY = {"freq": "daily", "time": "09:00"}


def make(client) -> dict:
    return client.post(f"{BASE}/lists/12/items", json={"text": "run the export"}).json()


def trigger_rows(env, item_id: int) -> int:
    with closing(service.store(env.ctx)._connect(False)) as conn:
        return conn.execute("SELECT COUNT(*) FROM work_item_triggers WHERE item_id = ?", (item_id,)).fetchone()[0]


def test_a_late_result_after_a_cancel_lands_unread_and_the_task_stays_cancelled(client, env):
    store = service.store(env.ctx)
    item = make(client)
    closure_undo.cancel_task(store, item["id"], item["revision"])
    assert store.item(item["id"])["unread"] is False
    late = store.post(item["id"], "export finished anyway", actor="claude", kind="info")
    assert late["item"]["unread"] is True and late["item"]["state"] == "done" and late["message"]["unread"] is True
    with pytest.raises(TaskManagerForbidden):
        store.update(item["id"], actor="claude", state="review")
    (row,) = client.get(f"{BASE}/closed").json()["items"]
    assert row["closure"]["outcome"] == "cancelled" and row["item"]["unread"] is True


def test_a_late_info_on_a_completed_task_stays_quiet(client, env):
    store = service.store(env.ctx)
    item = make(client)
    store.update(item["id"], actor="joe", state="done")
    assert store.post(item["id"], "a note", actor="claude", kind="info")["item"]["unread"] is False


def test_a_cancel_stops_a_repeating_schedule_and_closes_the_task(client, env):
    store = service.store(env.ctx)
    item = make(client)
    assert client.patch(f"{ITEMS}/{item['id']}", json={"repeat": DAILY}).status_code == 200
    assert trigger_rows(env, item["id"]) == 1
    fresh = store.item(item["id"])
    cancelled = closure_undo.cancel_task(store, item["id"], fresh["revision"])["item"]
    assert cancelled["state"] == "done" and trigger_rows(env, item["id"]) == 0 and "fire_at" not in (cancelled.get("trigger") or {})
    (row,) = client.get(f"{BASE}/closed").json()["items"]
    assert row["closure"]["outcome"] == "cancelled"


def test_an_ordinary_tick_of_a_repeating_task_still_returns_it_to_open(client, env):
    store = service.store(env.ctx)
    item = make(client)
    client.patch(f"{ITEMS}/{item['id']}", json={"repeat": DAILY})
    assert store.update(item["id"], actor="joe", state="done")["state"] == "open" and trigger_rows(env, item["id"]) == 1
