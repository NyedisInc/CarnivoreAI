
from __future__ import annotations

from fastapi.testclient import TestClient

from src.cplugs.huddle import told_log
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_send_queue import BASE, SEND, env, flush_due  # noqa: F401

SENT = f"{BASE}/sent"


def sends(client) -> dict:
    return client.get(SENT).json()["sends"][0]


def test_a_reply_reads_waiting_then_queued_then_told(client, app, env):
    told_log.reset()
    note(app, "ses_old", "12", 100.0)
    item = client.post(f"{BASE}/lists/12/items", json={"text": "check the build"}).json()["id"]
    client.post(f"{BASE}/lists/12/send", json={})
    env.clock.now = 1005.0
    client.post(f"{BASE}/items/{item}/messages", json={"text": "yes, ship it"})
    top = sends(client)
    assert (top["kind"], top["text"], top["item"]["id"], top["list_name"]) == ("reply", "yes, ship it", item, "carnivore")
    assert top["tell"]["state"] == "waiting" and top["session"] is None
    client.post(SEND, json={"lists": ["12"], "queue": True})
    queued = sends(client)["tell"]
    assert queued["state"] == "queued" and queued["due_at"] == 1015.0
    env.clock.now = 1015.0
    assert [o["status"] for o in flush_due(env)] == ["sent"]
    told = sends(client)["tell"]
    assert told["state"] == "told" and told["label"] == "ses_old" and told["at"] is not None
    assert sends(client)["session"] == "ses_old"
    told_log.reset()


def test_the_sent_route_needs_a_login(app):
    with TestClient(app) as anonymous:
        assert anonymous.get(SENT).status_code in (401, 403)
