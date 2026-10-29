
from __future__ import annotations

import json
from contextlib import closing

import pytest

from src.cplugs.huddle import lifecycle, service
from src.cplugs.huddle.wire import ITEM_COLS
from tests.python.cplugs.huddle.test_task_manager_routes import app, client  # noqa: F401

BASE = "/api/v1/cplugs/huddle"


@pytest.fixture
def seeded(client, app):
    ids = {}
    for name in "abcdefg":
        ids[name] = client.post(f"{BASE}/lists/12/items", json={"text": f"item {name}"}).json()["id"]
        client.post(f"{BASE}/items/{ids[name]}/messages", json={"text": f"reply on {name}"})
    for name in "bdf":
        client.patch(f"{BASE}/items/{ids[name]}", json={"approved": True})
    client.patch(f"{BASE}/items/{ids['e']}", json={"state": "review"})
    store = service.store(app.state.cplugs_host.context("huddle"))
    with closing(store._connect(True)) as conn, conn:
        conn.execute("UPDATE work_items SET claude_read_seq = joe_seq WHERE id NOT IN (?, ?)", (ids["f"], ids["g"]))
    return ids, store


def test_live_only_aggregate_omits_done_items_and_keeps_numbers_and_counts(seeded):
    ids, store = seeded
    full = store.aggregate(hide_swarm=True)["groups"][0]
    live = store.aggregate(hide_swarm=True, live_only=True)["groups"][0]
    plain_done = {ids["b"], ids["d"]}
    assert {i["id"] for i in full["items"]} == set(ids.values())
    assert {i["id"] for i in live["items"]} == set(ids.values()) - plain_done
    assert live["done_count"] == 2 and "done_count" not in full
    by_id = {i["id"]: i for i in full["items"]}
    assert all(i == by_id[i["id"]] for i in live["items"])
    assert {k: v for k, v in live.items() if k not in ("items", "done_count", "done_swarm")} == {k: v for k, v in full.items() if k != "items"}
    assert len(json.dumps(live)) < len(json.dumps(full))


def test_summary_counts_equal_the_full_row_counts(seeded):
    ids, store = seeded
    with closing(store._connect(False)) as conn:
        rows = conn.execute(f"SELECT {ITEM_COLS} FROM work_items WHERE deleted = 0").fetchall()
        asking = lifecycle.asking_ids(conn, [r["id"] for r in rows])
    row = store.summary()["lists"]["12"]
    assert row["items"] == 7 and row["open"] == 3 and row["review"] == 1 and row["waiting_to_send"] == 2
    assert row["waiting_to_send"] == lifecycle.waiting_counts(rows, asking)["12"]
    assert row["needs_you"] == lifecycle.needs_you_counts(rows, asking).get("12", 0)
    assert row["attention"] == lifecycle.attention_counts(rows, asking).get("12", 0)
    assert row["status_counts"] == lifecycle.status_counts(rows, asking)["12"]


def test_done_page_returns_the_omitted_items_a_page_at_a_time(seeded):
    ids, store = seeded
    first = store.done_page("12", limit=1)
    assert first["total"] == 2 and first["next_offset"] == 1 and [i["id"] for i in first["items"]] == [ids["b"]]
    assert first["items"][0]["number"] is None and [m["text"] for m in first["items"][0]["thread"] if not m.get("category")] == ["reply on b"]
    last = store.done_page("12", limit=1, offset=1)
    assert [i["id"] for i in last["items"]] == [ids["d"]] and last["next_offset"] is None
    live = {i["id"] for i in store.list_items("12", live_only=True)["items"]}
    assert live | {ids["b"], ids["d"]} == set(ids.values())


def test_the_done_route_is_authenticated_paged_and_slim(client, app, seeded):
    ids, _store = seeded
    page = client.get(f"{BASE}/lists/12/done", params={"limit": 1}).json()
    assert page["total"] == 2 and page["next_offset"] == 1 and page["items"][0]["id"] == ids["b"] and page["items"][0]["thread_count"] == 2
    assert client.get(f"{BASE}/lists/12/done", params={"limit": 0}).status_code == 422
    assert client.get(f"{BASE}/lists/bad/done").status_code == 400
    live = client.get(f"{BASE}/aggregate", params={"live_only": 1}).json()["groups"][0]
    assert live["done_count"] == 2 and ids["b"] not in {i["id"] for i in live["items"]}
    one = client.get(f"{BASE}/lists/12", params={"live_only": 1}).json()
    assert one["done_count"] == 2 and ids["d"] not in {i["id"] for i in one["items"]}
    app.dependency_overrides.clear()
    from fastapi.testclient import TestClient
    with TestClient(app) as anonymous:
        assert anonymous.get(f"{BASE}/lists/12/done").status_code in (401, 403)


def test_a_reorder_built_from_the_live_read_leaves_the_done_items_in_their_slots(client, seeded):
    ids, store = seeded
    read = client.get(f"{BASE}/lists/12", params={"live_only": 1}).json()
    order = [i["id"] for i in read["items"]][::-1]
    moved = client.put(f"{BASE}/lists/12/order", json={"ids": order, "expected_revision": read["revision"]})
    assert moved.status_code == 200
    full = [i["id"] for i in store.list_items("12")["items"]]
    assert [i for i in full if i in order] == order
    assert {ids["b"], ids["d"]} <= set(full)
    stale = client.put(f"{BASE}/lists/12/order", json={"ids": order[:-1], "expected_revision": read["revision"]})
    assert stale.status_code == 409
