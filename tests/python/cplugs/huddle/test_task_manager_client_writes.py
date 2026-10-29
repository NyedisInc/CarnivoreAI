
from __future__ import annotations

from src.cplugs.huddle import client_writes, service
from tests.python.cplugs.huddle.test_task_manager_routes import app, client  # noqa: F401

BASE = "/api/v1/cplugs/huddle"


def reply_count(client, item_id: int) -> int:
    return sum(1 for m in client.get(f"{BASE}/items/{item_id}").json()["thread"] if m["author"] == "joe")


def test_a_retried_reply_lands_once_even_after_a_restart(client):
    client_writes.reset()
    item = client.post(f"{BASE}/lists/12/items", json={"text": "check the build"}).json()["id"]
    url = f"{BASE}/items/{item}/messages"
    first = client.post(url, json={"text": "yes, ship it", "client_id": "outbox-aaaa1111"}).json()
    assert first["duplicate"] is False and reply_count(client, item) == 1
    again = client.post(url, json={"text": "yes, ship it", "client_id": "outbox-aaaa1111", "retry_age_s": 2}).json()
    assert again["duplicate"] is True and again["message"]["id"] == first["message"]["id"] and reply_count(client, item) == 1
    client_writes.reset()
    late = client.post(url, json={"text": "yes, ship it", "client_id": "outbox-aaaa1111", "retry_age_s": 5}).json()
    assert late["duplicate"] is True and late["message"]["id"] == first["message"]["id"] and reply_count(client, item) == 1
    client_writes.reset()
    repeat = client.post(url, json={"text": "yes, ship it", "client_id": "outbox-bbbb2222"}).json()
    assert repeat["duplicate"] is False and reply_count(client, item) == 2
    assert client.post(url, json={"text": "x", "client_id": "bad id!"}).status_code == 400


def test_a_retried_add_box_entry_is_one_entry_and_a_changed_answer_is_a_replay_not_a_conflict(client):
    client_writes.reset()
    url = f"{BASE}/lists/12/inbox"
    first = client.post(url, json={"text": "fix the footer", "client_id": "outbox-cccc3333"}).json()
    assert first["duplicate"] is False and first["queued"] is True
    client_writes.reset()
    again = client.post(url, json={"text": "fix the footer", "client_id": "outbox-cccc3333", "retry_age_s": 9}).json()
    assert again["duplicate"] is True and again["entry"]["id"] == first["entry"]["id"]
    assert len(client.get(f"{BASE}/inbox", params={"list": "12"}).json()["entries"]) == 1
