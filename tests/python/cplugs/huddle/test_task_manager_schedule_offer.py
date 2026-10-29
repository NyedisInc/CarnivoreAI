
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.cplugs.host import runtime
from src.cplugs.huddle import schedule_offer
from src.cplugs.huddle.rules import CLAUDE, JOE, TaskManagerInvalid, TaskManagerNotFound
from src.cplugs.huddle.store import TaskManagerStore
from tests.python.cplugs.huddle.test_task_manager_mcp import CALLER, call, huddle_store, manager  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, pasted  # noqa: F401


def soon(days: int = 7) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat()


def test_clean_validates_and_normalizes():
    out = schedule_offer.clean({"when": soon(), "title": "  delete the moved files "})
    assert out["state"] == "offered" and out["title"] == "delete the moved files"
    for bad in ({"when": soon()}, {"when": "2020-01-01T00:00:00Z", "title": "x"}, {"when": "2030-01-01T00:00:00", "title": "x"},
                {"when": soon(), "title": "x", "extra": 1}, "tomorrow", {"when": soon(), "title": " "}):
        with pytest.raises(TaskManagerInvalid):
            schedule_offer.clean(bad)


def test_attach_keeps_a_quote_first_and_read_round_trips():
    offer = schedule_offer.clean({"when": soon(), "title": "t"})
    parts = schedule_offer.attach('{"quote": {"id": 1, "text": "q"}}', offer)
    assert parts.startswith('{"quote"') and schedule_offer.read(parts) == offer
    assert schedule_offer.read("") is None and schedule_offer.read('{"schedule": 5}') is None and schedule_offer.read("{bad schedule") is None


def test_an_agent_reply_carries_an_offer_and_a_bad_offer_writes_nothing(manager):
    ok, item = call(manager, "task_manager_add", {"list": "mine", "text": "moved the files"})
    offer = {"when": soon(), "title": "delete the moved files"}
    ok, posted = call(manager, "task_manager_reply", {"item": item["id"], "text": "keeping them a week", "offer_schedule": offer})
    assert ok
    sent = [m for m in huddle_store(manager).item(item["id"])["thread"] if m["author"] == CLAUDE]
    assert sent[-1]["schedule"]["title"] == "delete the moved files" and sent[-1]["schedule"]["state"] == "offered"
    count = len(huddle_store(manager).item(item["id"])["thread"])
    ok, text = call(manager, "task_manager_reply", {"item": item["id"], "text": "again", "offer_schedule": {"when": "2020-01-01T00:00:00Z", "title": "x"}})
    assert not ok and "future" in text
    assert len(huddle_store(manager).item(item["id"])["thread"]) == count


def test_owner_accepts_once_and_the_agent_is_cued_on_the_thread(client, app, pasted):
    store = TaskManagerStore(runtime.host_for(app).storage("huddle"), notify=lambda key: None)
    item = client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "moved files"}).json()["id"]
    when = soon()
    message = store.post(item, "keeping them a week", actor=CLAUDE, offer=schedule_offer.clean({"when": when, "title": "delete them"}))["message"]
    url = f"/api/v1/cplugs/huddle/items/{item}/messages/{message['id']}/schedule"
    done = client.post(url)
    assert done.status_code == 200
    body = done.json()
    assert body["offer"]["state"] == "accepted" and body["message"]["schedule"]["accepted_at"]
    assert body["reply"]["author"] == JOE and f"fire_at={body['offer']['when']}" in body["reply"]["text"] and "delete them" in body["reply"]["text"]
    stored = [m for m in client.get(f"/api/v1/cplugs/huddle/items/{item}").json()["thread"] if m["id"] == message["id"]]
    assert stored[0]["schedule"]["state"] == "accepted"
    assert client.post(url).status_code == 400
    assert client.post(f"/api/v1/cplugs/huddle/items/{item}/messages/999999/schedule").status_code == 404
    plain = store.post(item, "no offer here", actor=CLAUDE)["message"]
    assert client.post(f"/api/v1/cplugs/huddle/items/{item}/messages/{plain['id']}/schedule").status_code == 404


def test_owner_cannot_attach_an_offer_and_an_offer_in_the_past_is_refused_at_accept(client, app):
    store = TaskManagerStore(runtime.host_for(app).storage("huddle"), notify=lambda key: None)
    item = client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "x"}).json()["id"]
    with pytest.raises(TaskManagerInvalid):
        store.post(item, "mine", actor=JOE, offer={"when": soon(), "title": "t", "state": "offered"})
    stale = store.post(item, "late", actor=CLAUDE, offer={"when": "2020-01-01T00:00:00+00:00", "title": "t", "state": "offered"})["message"]
    assert client.post(f"/api/v1/cplugs/huddle/items/{item}/messages/{stale['id']}/schedule").status_code == 400
