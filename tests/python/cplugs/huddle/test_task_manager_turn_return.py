
from __future__ import annotations

import asyncio
from contextlib import closing

import pytest

from src.cplugs.host import runtime
from src.cplugs.huddle import lineage, turn_return
from tests.python.cplugs.huddle.roles_rig import BASE
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note, pasted  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_tags import World, add, store_of  # noqa: F401


@pytest.fixture
def world(app, monkeypatch, pasted):
    note(app, "ses_old", "12", 100.0)
    return World(app, monkeypatch)


def status_of(world, status: str, session: str = "ses_old") -> None:
    next(r for r in world.live if r.session.id == session).activity_status = status


def turn_ends(world, session: str = "ses_old") -> list:
    ctx = runtime.host_for(world.app).context("huddle", background=True)
    return asyncio.run(turn_return.on_turn_end(ctx, session))


def replied_and_told(client, world, item: int, text: str = "why?") -> None:
    assert client.post(f"{BASE}/items/{item}/messages", json={"text": text}).status_code == 200
    assert client.post(f"{BASE}/send", json={"lists": ["12"]}).json()["results"][0]["status"] == "sent"


def history(world, item: int) -> list:
    with closing(store_of(world.app)._connect(False)) as conn:
        return [(r["from"], r["to"], r["by"], r["detail"]) for r in lineage.for_item(conn, item)]


def review_item(client, world) -> int:
    item = add(client)
    store_of(world.app).update(item, actor="claude", state="review")
    return item


def test_an_unanswered_review_reply_goes_back_to_review_when_the_turn_ends(client, world):
    item = review_item(client, world)
    replied_and_told(client, world, item)
    assert store_of(world.app).item(item)["state"] == "open"
    status_of(world, "idle")
    assert turn_ends(world) == [item]
    got = store_of(world.app).item(item)
    assert got["state"] == "review" and "did not answer" in got["thread"][-1]["text"] and got["thread"][-1]["kind"] == "info"
    assert history(world, item)[-1][2:] == ("carnivore", "turn ended unanswered, back")
    assert turn_ends(world) == []


def test_an_unanswered_done_reply_goes_back_to_done_as_a_restore_not_a_tick(client, world):
    item = add(client)
    store_of(world.app).update(item, actor="joe", approve=True)
    replied_and_told(client, world, item)
    status_of(world, "finished_unread")
    assert turn_ends(world) == [item]
    assert store_of(world.app).item(item)["state"] == "done" and history(world, item)[-1][2] == "carnivore"


def test_an_answered_task_is_left_for_the_session_to_return(client, world):
    item = review_item(client, world)
    replied_and_told(client, world, item)
    store_of(world.app).post(item, "because", actor="claude", kind="info")
    status_of(world, "idle")
    assert turn_ends(world) == [] and store_of(world.app).item(item)["state"] == "open"


@pytest.mark.parametrize("status", ["working", "working_subagent", "unknown", "dead"])
def test_a_status_that_is_not_a_measured_rest_does_nothing(client, world, status):
    item = review_item(client, world)
    replied_and_told(client, world, item)
    status_of(world, status)
    assert turn_ends(world) == [] and store_of(world.app).item(item)["state"] == "open"


def test_a_gone_session_a_claimed_task_and_an_untold_reply_do_nothing(client, world):
    item = review_item(client, world)
    assert client.post(f"{BASE}/items/{item}/messages", json={"text": "why?"}).status_code == 200
    status_of(world, "idle")
    assert turn_ends(world) == [] and turn_ends(world, "ses_nowhere") == []
    assert client.post(f"{BASE}/send", json={"lists": ["12"]}).json()["results"][0]["status"] == "sent"
    store_of(world.app).mark_working(item, "ses_old")
    assert turn_ends(world) == [] and store_of(world.app).item(item)["state"] == "open"


def test_another_sessions_turn_end_does_not_return_the_task(client, world):
    item = review_item(client, world)
    replied_and_told(client, world, item)
    status_of(world, "idle", "ses_new")
    assert turn_ends(world, "ses_new") == [] and store_of(world.app).item(item)["state"] == "open"
