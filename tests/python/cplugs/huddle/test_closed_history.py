
from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest

from src.cplugs.huddle import closures
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.storage import WorkStorage


class Clock:

    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(tmp_path: Path, clock: Clock) -> TaskManagerStore:
    return TaskManagerStore(WorkStorage(tmp_path), notify=lambda _key: None, clock=clock)


def close(store: TaskManagerStore, clock: Clock, text: str, at: float) -> int:
    item = store.add("all", text, actor="joe")["id"]
    clock.now = at
    store.update(item, actor="joe", state="done")
    return item


def page(store: TaskManagerStore, **kwargs) -> dict:
    with closing(store._connect(False)) as conn:
        return closures.page(conn, **kwargs)


def ids(body: dict) -> list:
    return [row["item"]["id"] for row in body["items"]]


def test_a_later_message_never_changes_closure_order(store, clock):
    a = close(store, clock, "first closed", 100.0)
    b = close(store, clock, "second closed", 200.0)
    assert ids(page(store)) == [b, a]
    clock.now = 900.0
    store.post(a, "a late result", actor="claude", kind="attention")
    store.post(a, "and a reply", actor="joe", kind="comment")
    assert ids(page(store)) == [b, a]


def test_equal_closure_times_order_by_id_newest_first(store, clock):
    first = close(store, clock, "one", 500.0)
    second = close(store, clock, "two", 500.0)
    third = close(store, clock, "three", 500.0)
    assert ids(page(store)) == [third, second, first]


def test_each_row_carries_closed_at_closed_by_and_outcome(store, clock):
    item = close(store, clock, "shipped", 321.0)
    (row,) = page(store)["items"]
    assert row["closure"]["closed_at"] == 321.0 and row["closure"]["closed_by"] == "owner" and row["closure"]["outcome"] == "completed"
    assert row["closure"]["known"] is True and row["item"]["id"] == item and row["item"]["thread"] == []


def test_cursor_pages_never_repeat_or_skip_even_when_a_task_closes_between_pages(store, clock):
    made = [close(store, clock, f"task {n}", 100.0 + n) for n in range(5)]
    first = page(store, limit=2)
    assert ids(first) == [made[4], made[3]] and first["next_cursor"]
    newest = close(store, clock, "closed between pages", 900.0)
    second = page(store, limit=2, cursor=first["next_cursor"])
    third = page(store, limit=2, cursor=second["next_cursor"])
    assert ids(second) == [made[2], made[1]] and ids(third) == [made[0]] and third["next_cursor"] is None
    assert newest not in ids(second) + ids(third)


def test_search_covers_title_description_and_the_whole_conversation(store, clock):
    by_text = close(store, clock, "reconcile the invoices", 100.0)
    by_thread = close(store, clock, "unrelated chore", 200.0)
    store.post(by_thread, "the zebra export finished", actor="claude", kind="info")
    close(store, clock, "no match here", 300.0)
    assert ids(page(store, q="INVOICES")) == [by_text]
    assert ids(page(store, q="zebra")) == [by_thread]
    assert ids(page(store, q="zebra export")) == [by_thread]
    assert ids(page(store, q="zebra invoices")) == []
    assert ids(page(store, q="100%")) == []


def test_open_tasks_and_a_reopened_task_are_not_listed(store, clock):
    store.add("all", "still open", actor="joe")
    item = close(store, clock, "closed then reopened", 100.0)
    assert ids(page(store)) == [item]
    store.update(item, actor="joe", state="open")
    assert ids(page(store)) == []


def test_a_task_closed_before_the_log_has_no_time_and_sorts_last(store, clock):
    dated = close(store, clock, "dated", 100.0)
    old = close(store, clock, "predates the log", 50.0)
    with closing(store._connect(True)) as conn, conn:
        conn.execute("DELETE FROM work_card_events WHERE item_id = ? AND kind = 'state'", (old,))
    body = page(store)
    assert ids(body) == [dated, old]
    assert body["items"][1]["closure"] == {"id": None, "closed_at": None, "closed_by": None, "outcome": "completed", "known": False, "can_undo": False}
    assert ids(page(store, limit=1, cursor=page(store, limit=1)["next_cursor"])) == [old]


def test_a_cursor_this_list_did_not_issue_is_refused(store):
    with pytest.raises(closures.CursorError):
        page(store, cursor="not-a-cursor")


from tests.python.cplugs.huddle.test_task_manager_routes import app, client  # noqa: E402,F401

CLOSED = "/api/v1/cplugs/huddle/closed"
ITEMS = "/api/v1/cplugs/huddle/lists/all/items"


def test_the_route_pages_searches_and_refuses_a_bad_cursor(client):
    made = [client.post(ITEMS, json={"text": f"route task {n}"}).json() for n in range(3)]
    for item in made:
        assert client.patch(f"/api/v1/cplugs/huddle/items/{item['id']}", json={"state": "done"}).status_code == 200
    first = client.get(CLOSED, params={"limit": 2}).json()
    assert [r["item"]["id"] for r in first["items"]] == [made[2]["id"], made[1]["id"]] and first["next_cursor"]
    rest = client.get(CLOSED, params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert [r["item"]["id"] for r in rest["items"]] == [made[0]["id"]] and rest["next_cursor"] is None
    assert [r["item"]["id"] for r in client.get(CLOSED, params={"q": "task 1"}).json()["items"]] == [made[1]["id"]]
    bad = client.get(CLOSED, params={"cursor": "zzz"})
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "closed_cursor_invalid"
    assert client.get(CLOSED, params={"limit": 0}).status_code == 422
