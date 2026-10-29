
from __future__ import annotations

import asyncio
from contextlib import closing

import pytest

from src.cplugs.huddle import rules, send_queue
from src.cplugs.huddle.nudge_store import NudgeStore
from src.cplugs.huddle.rules import CLAUDE, JOE
from tests.python.cplugs.huddle.test_task_manager_routes import _store, app, client, note  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_send_queue import BASE, SEND, env  # noqa: F401

SWARM_REFS = ("chat", "trust:4:ab")


def owner_line(app, ref: str) -> int:
    store = _store(app)
    item = store.add("12", "swarm thread", actor=CLAUDE, created_key=rules.SWARM_KEY, swarm_ref=ref)
    store.post(item["id"], "use pytest", actor=JOE, kind=rules.REPLY, author_key=rules.OWNER_KEY)
    return item["id"]


def told_state(app, env) -> tuple:
    store = _store(app)
    entry = store.summary()["lists"].get("12", {})
    waiting = [i["id"] for i in store.list_items("12")["items"] if i["status"] == "waiting_to_send"]
    return bool(entry.get("untold")), entry.get("waiting_to_send", 0), [i for i, _key in store.untold_owners("12")], waiting


@pytest.mark.parametrize("ref", SWARM_REFS)
def test_an_owner_write_on_a_swarm_thread_item_is_never_unsent_and_a_plain_task_still_is(client, app, env, ref):
    note(app, "ses_old", "12", 100.0)
    swarm_item = owner_line(app, ref)
    with closing(_store(app)._connect(False)) as conn:
        assert conn.execute("SELECT joe_seq FROM work_items WHERE id = ?", (swarm_item,)).fetchone()[0] > 0
    assert told_state(app, env) == (False, 0, [], [])
    assert asyncio.run(send_queue.rearm_untold(env.ctx)) == []
    send_queue.queue_change(env.ctx, "12")
    outcome = asyncio.run(send_queue.flush_now(env.ctx))
    assert [(o["list"], o["status"]) for o in outcome] == [("12", "nothing")] and env.pasted == []

    task = client.post(f"{BASE}/lists/12/items", json={"text": "a task of Joe's"}).json()["id"]
    assert told_state(app, env) == (True, 1, [task], [task])
    assert asyncio.run(send_queue.rearm_untold(env.ctx)) == ["12"]
    outcome = asyncio.run(send_queue.flush_now(env.ctx))
    assert [(o["list"], o["status"]) for o in outcome] == [("12", "sent")] and len(env.pasted) == 1


@pytest.mark.parametrize("ref", SWARM_REFS)
def test_a_plain_change_on_a_swarm_thread_item_is_not_queued_so_the_key_never_shows_a_send_that_will_not_happen(client, app, env, ref):
    owner_line(app, ref)
    answer = client.post(SEND, json={"lists": ["12"], "queue": True}).json()
    assert [(r["list"], r["status"]) for r in answer["results"]] == [("12", "nothing")]
    assert asyncio.run(send_queue.flush_now(env.ctx)) == [] and env.pasted == []

    client.post(f"{BASE}/lists/12/items", json={"text": "a task of Joe's"})
    answer = client.post(SEND, json={"lists": ["12"], "queue": True}).json()
    assert [(r["list"], r["status"]) for r in answer["results"]] == [("12", "queued")]


@pytest.mark.parametrize("ref", SWARM_REFS)
def test_the_nudge_never_picks_up_a_swarm_thread_item(client, app, env, ref):
    swarm_item = owner_line(app, ref)
    task = client.post(f"{BASE}/lists/12/items", json={"text": "a task of Joe's"}).json()["id"]
    ids = [row["id"] for row, _status, _last, _basis in NudgeStore(_store(app)).candidates("12")]
    assert task in ids and swarm_item not in ids
