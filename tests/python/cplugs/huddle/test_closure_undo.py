
from __future__ import annotations

import asyncio
from contextlib import closing

import pytest

from src.cplugs.huddle import send_queue, service
from src.cplugs.huddle.cards import state_log
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_send_queue import env, flush_due  # noqa: F401

BASE = "/api/v1/cplugs/huddle"
ITEMS = f"{BASE}/items"


def make(client, text: str = "ship it") -> dict:
    return client.post(f"{BASE}/lists/12/items", json={"text": text}).json()


def tick(client, item: dict) -> dict:
    return client.patch(f"{ITEMS}/{item['id']}", json={"state": "done", "expected_revision": item["revision"]}).json()


def undo(client, item_id: int, revision: int):
    return client.post(f"{ITEMS}/{item_id}/undo-completion", json={"expected_revision": revision})


def log(env, item_id: int) -> list:
    store = service.store(env.ctx)
    with closing(store._connect(False)) as conn:
        return [(r["from"], r["to"], r["by"], r["detail"]) for r in state_log.for_item(conn, item_id)]


def test_undo_after_only_messages_succeeds_restores_the_state_and_queues_the_retraction(client, app, env):
    note(app, "ses_old", "12", 100.0)
    item = make(client)
    closed = tick(client, item)
    assert closed["state"] == "done"
    service.store(env.ctx).post(item["id"], "late result", actor="claude", kind="attention")
    service.store(env.ctx).post(item["id"], "my note", actor="joe", kind="comment")
    answer = undo(client, item["id"], closed["revision"])
    assert answer.status_code == 200
    body = answer.json()
    assert body["item"]["state"] == "open"
    retraction = body["retraction"]
    assert retraction["text"] == "completion withdrawn" and retraction["delivery_id"] == f"m:{retraction['message_id']}"
    assert retraction["status"] == "queued" and retraction["due_at"] is not None
    thread = client.get(f"{ITEMS}/{item['id']}").json()["thread"]
    correction = [m for m in thread if m["kind"] == "correction"]
    assert len(correction) == 1 and correction[0]["author"] == "joe" and correction[0]["retracts"]["outcome"] == "completed"
    assert correction[0]["retracts"]["restored_state"] == "open"
    history = log(env, item["id"])
    assert history[-2][1:3] == ("done", "owner") and history[-1] == ("done", "open", "owner", "undo completion")


def test_undo_after_the_task_moved_is_refused_with_a_reason(client, app, env):
    item = make(client)
    closed = tick(client, item)
    reopened = client.patch(f"{ITEMS}/{item['id']}", json={"state": "open", "expected_revision": closed["revision"]}).json()
    refused = undo(client, item["id"], reopened["revision"])
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "task_manager_not_allowed" and refused.json()["detail"]["reason"] == "not_closed"
    stale = undo(client, item["id"], closed["revision"])
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "task_manager_stale" and stale.json()["detail"]["current"]["state"] == "open"


def test_undo_when_a_state_move_came_after_the_closure_is_refused(client, app, env):
    item = make(client)
    closed = tick(client, item)
    store = service.store(env.ctx)
    with closing(store._connect(True)) as conn, conn:
        state_log.write(conn, item["id"], "12", "done", "review", by="agent:7", now=env.clock.now + 5)
    refused = undo(client, item["id"], closed["revision"])
    assert refused.status_code == 409 and refused.json()["detail"]["reason"] == "moved"


def test_only_the_newest_closure_can_be_undone_and_a_double_click_is_stale(client, app, env):
    item = make(client)
    first = tick(client, item)
    reopened = client.patch(f"{ITEMS}/{item['id']}", json={"state": "open", "expected_revision": first["revision"]}).json()
    second = tick(client, reopened)
    assert undo(client, item["id"], second["revision"]).status_code == 200
    assert undo(client, item["id"], second["revision"]).status_code == 409


def test_cancel_closes_with_outcome_cancelled_and_undo_sends_cancellation_withdrawn(client, app, env):
    note(app, "ses_old", "12", 100.0)
    item = make(client)
    cancelled = client.post(f"{ITEMS}/{item['id']}/cancel", json={"expected_revision": item["revision"], "note": "wrong plan"})
    assert cancelled.status_code == 200 and cancelled.json()["item"]["state"] == "done"
    assert cancelled.json()["notice"]["text"] == "task cancelled: wrong plan" and cancelled.json()["notice"]["status"] == "queued"
    (row,) = client.get(f"{BASE}/closed").json()["items"]
    assert row["closure"]["outcome"] == "cancelled" and row["closure"]["closed_by"] == "owner" and row["closure"]["can_undo"] is True
    again = client.post(f"{ITEMS}/{item['id']}/cancel", json={"expected_revision": cancelled.json()["item"]["revision"]})
    assert again.status_code == 409 and again.json()["detail"]["reason"] == "already_closed"
    withdrawn = undo(client, item["id"], cancelled.json()["item"]["revision"]).json()
    assert withdrawn["retraction"]["text"] == "cancellation withdrawn" and withdrawn["item"]["state"] == "open"
    assert client.get(f"{BASE}/closed").json()["items"] == []


def test_a_prior_review_state_comes_back_review_and_a_prior_wait_comes_back_open(client, app, env):
    store = service.store(env.ctx)
    reviewed = make(client, "reviewed")
    store.update(reviewed["id"], actor="claude", state="review", review_fields={"review_summary": "done", "review_description": "see it"})
    closed = tick(client, client.get(f"{ITEMS}/{reviewed['id']}").json())
    assert undo(client, reviewed["id"], closed["revision"]).json()["item"]["state"] == "review"
    waiting = make(client, "waiting")
    store.update(waiting["id"], actor="claude", state="waiting", wait={"waiting_on": "the vendor", "wait_kind": "vendor"}, wait_by="u-1")
    closed = tick(client, client.get(f"{ITEMS}/{waiting['id']}").json())
    assert undo(client, waiting["id"], closed["revision"]).json()["item"]["state"] == "open"


def test_the_retraction_survives_a_restart_and_is_told_once_the_window_closes(client, app, env):
    note(app, "ses_old", "12", 100.0)
    item = make(client)
    closed = tick(client, item)
    client.post(f"{BASE}/send", json={"lists": ["12"]})
    env.pasted.clear()
    body = undo(client, item["id"], closed["revision"]).json()
    delivery = body["retraction"]["delivery_id"]
    send_queue.reset()
    assert client.get(f"{BASE}/send-queue").json()["count"] == 0
    assert asyncio.run(send_queue.rearm_untold(env.ctx)) == ["12"]
    sends = {s["key"]: s for s in client.get(f"{BASE}/sent").json()["sends"]}
    assert sends[delivery]["kind"] == "correction" and sends[delivery]["tell"]["state"] == "queued"
    env.clock.now += 20
    assert [o["status"] for o in flush_due(env)] == ["sent"] and len(env.pasted) == 1
    sends = {s["key"]: s for s in client.get(f"{BASE}/sent").json()["sends"]}
    assert sends[delivery]["tell"]["state"] == "told"


def test_a_closure_before_the_log_cannot_be_undone(client, app, env):
    item = make(client)
    closed = tick(client, item)
    store = service.store(env.ctx)
    with closing(store._connect(True)) as conn, conn:
        conn.execute("DELETE FROM work_card_events WHERE item_id = ? AND kind = 'state'", (item["id"],))
    refused = undo(client, item["id"], closed["revision"])
    assert refused.status_code == 409 and refused.json()["detail"]["reason"] == "moved"
