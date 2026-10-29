
from __future__ import annotations

import pytest

from src.cplugs.huddle import item_owner
from src.cplugs.huddle.roles import dnd_gate, tags
from tests.python.cplugs.huddle.roles_rig import BASE
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note, pasted  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_tags import World, add, run, store_of

REASON = "requested me in chat to take this one"


@pytest.fixture
def world(app, client, monkeypatch, pasted):
    note(app, "ses_old", "12", 100.0)
    made = World(app, monkeypatch)
    assert client.put(f"{BASE}/sessions/ses_new/dnd", json={"dnd": True}).status_code == 200
    return made


def thread(world, item: int) -> list:
    from contextlib import closing
    with closing(store_of(world.app)._connect(False)) as conn:
        return [dict(r) for r in conn.execute("SELECT kind, text, author_key FROM work_messages WHERE item_id = ? ORDER BY id", (item,))]


@pytest.mark.parametrize("name, extra", [
    ("task_manager_update", {"state": "working"}),
    ("task_manager_update", {"tag": "me"}),
    ("task_manager_update", {"text": "rewrite"}),
    ("task_manager_reply", {"text": "here is my work", "kind": "info"}),
    ("task_manager_progress_set", {"phase": "running"}),
    ("task_manager_fork", {"text": "a copy"}),
])
def test_a_dnd_agent_is_refused_on_a_task_that_is_not_its_own(client, world, name, extra):
    item = add(client)
    ok, error = run(world.app, name, {"item": item, **extra})
    assert not ok and dnd_gate.CODE in error and "do not disturb" in error and "task_manager_ask" in error and "reason" in error
    stored = store_of(world.app).item(item)
    assert stored[item_owner.TAG_COLUMN] == "" and stored["status"] != "working"


def test_a_refused_claim_writes_nothing_and_a_short_reason_is_not_enough(client, world):
    item = add(client)
    before = store_of(world.app).item(item)["revision"]
    ok, error = run(world.app, "task_manager_update", {"item": item, "state": "working", "reason": "because"})
    assert not ok and dnd_gate.CODE in error and store_of(world.app).item(item)["revision"] == before


def test_a_reason_lets_the_claim_through_and_is_posted_for_the_owner(client, world):
    item = add(client)
    ok, body = run(world.app, "task_manager_update", {"item": item, "state": "working", "reason": REASON})
    assert ok and body["status"] == "working"
    infos = [m for m in thread(world, item) if REASON in m["text"]]
    assert len(infos) == 1 and infos[0]["kind"] == "info" and infos[0]["author_key"] == "ses_new"
    assert run(world.app, "task_manager_update", {"item": item, "state": "review"})[0]


def test_an_ask_is_never_gated_and_the_owners_answer_lets_the_agent_in(client, world):
    item = add(client)
    assert run(world.app, "task_manager_ask", {"item": item, "text": "may I take this one?"})[0]
    assert not run(world.app, "task_manager_update", {"item": item, "state": "working"})[0]
    assert client.post(f"{BASE}/items/{item}/messages", json={"text": "yes, take it"}).status_code == 200
    assert run(world.app, "task_manager_update", {"item": item, "state": "working"})[0]


def test_a_task_tagged_to_the_agent_by_the_owner_works_as_today(client, world):
    item = add(client)
    tags.set_tag(store_of(world.app), item, "ses_new")
    for name, args in (("task_manager_update", {"state": "working"}), ("task_manager_reply", {"text": "on it", "kind": "info"})):
        assert run(world.app, name, {"item": item, **args})[0], name


def test_a_task_the_agent_created_itself_is_its_own(world):
    ok, made = run(world.app, "task_manager_add", {"list": "12", "text": "my own follow-up"})
    assert ok
    assert run(world.app, "task_manager_update", {"item": made["item_id"], "state": "working"})[0]


def test_the_batch_ops_are_judged_one_by_one(client, world):
    item = add(client)
    ok, body = run(world.app, "task_manager_batch_run", {"list_id": "12", "ops": [{"op": "update", "item_id": item, "state": "working"}]})
    assert dnd_gate.CODE in str(body) and store_of(world.app).item(item)["status"] != "working"


def test_an_agent_not_on_do_not_disturb_is_not_gated(client, world):
    item = add(client)
    client.put(f"{BASE}/sessions/ses_new/dnd", json={"dnd": False})
    assert run(world.app, "task_manager_update", {"item": item, "state": "working"})[0]
