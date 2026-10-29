
from __future__ import annotations

import asyncio
import json
from contextlib import closing

import pytest
from fastapi import HTTPException

from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.cplugs.host import runtime, session_actions
from src.cplugs.huddle import item_owner, lineage, service
from src.cplugs.huddle.roles import ask
from src.cplugs.huddle.store import TaskManagerStore
from tests.python.cplugs.huddle.roles_rig import BASE, aged, give_asleep, give_rows
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note, pasted  # noqa: F401

SEND = f"{BASE}/send"
NEW = AgentCaller("ses_new", "cloude_new", "ses_new")
SLEEPER = "ses_sleeper"


def store_of(app) -> TaskManagerStore:
    return TaskManagerStore(runtime.host_for(app).storage("huddle"), notify=lambda key: None)


class World:

    def __init__(self, app, monkeypatch) -> None:
        self.app, self.live, self.asleep, self.woken = app, [aged("ses_old", 12, 5), aged("ses_new", 12, 1), aged("ses_other", 99, 3)], [], []
        self.refuse_wake = False
        give_rows(app, self.live)
        give_asleep(monkeypatch, self.asleep)

        async def wake(request, session_uuid):
            self.woken.append(session_uuid)
            if self.refuse_wake:
                raise HTTPException(status_code=409, detail={"code": "wake_refused"})
            self.asleep[:] = [s for s in self.asleep if s["session_uuid"] != session_uuid]
            self.live.append(aged(session_uuid, 12, 0))
            return {"status": "started"}

        monkeypatch.setattr(session_actions, "wake", wake)

    def sleeper(self) -> None:
        self.asleep.append({"session_uuid": SLEEPER, "project_id": 12, "name": "sleeper"})


@pytest.fixture
def world(app, monkeypatch, pasted):
    note(app, "ses_old", "12", 100.0)
    return World(app, monkeypatch)


def add(client, text: str = "build it") -> int:
    return client.post(f"{BASE}/lists/12/items", json={"text": text}).json()["id"]


def told_once(client) -> None:
    assert client.post(SEND, json={"lists": ["12"]}).json()["results"][0]["status"] == "sent"


def joe_reply(client, item: int) -> None:
    assert client.post(f"{BASE}/items/{item}/messages", json={"text": "see my note"}).status_code == 200


def tag(client, item: int, session):
    return client.put(f"{BASE}/items/{item}/tag", json={"session": session})


def run(app, name: str, args: dict, caller: AgentCaller = NEW):
    result = asyncio.run(tools.call_tool(app.state.session_manager, caller, name, {"lean": False, **args} if name == "task_manager_update" else args))
    text = result["content"][0]["text"]
    return (False, text) if result.get("isError") else (True, json.loads(text))


def test_rung_45_adds_the_tag_column_and_its_partial_index(client, world):
    with closing(store_of(world.app)._connect(False)) as conn:
        assert "tagged_session_key" in {r[1] for r in conn.execute("PRAGMA table_info(work_items)")}
        index = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'work_items_tagged'").fetchone()[0]
    assert "tagged_session_key != ''" in index
    assert add(client) and store_of(world.app).item(1)[item_owner.TAG_COLUMN] == ""


def test_the_owner_route_sets_and_clears_a_tag_and_refuses_what_cannot_take_one(client, world):
    item = add(client)
    assert tag(client, item, "ses_other").json()[item_owner.TAG_COLUMN] == "ses_other"
    assert tag(client, item, None).json()[item_owner.TAG_COLUMN] == ""
    assert tag(client, item, "remote:peer-abc").status_code == 400
    assert tag(client, item, "ses_nowhere").status_code == 400
    client.put(f"{BASE}/sessions/ses_new/dnd", json={"dnd": True})
    assert tag(client, item, "ses_new").status_code == 400
    assert tag(client, 9999, "ses_other").status_code == 404
    assert client.put(f"{BASE}/items/{item}/tag", json={}).status_code == 422


def test_an_agent_tags_itself_with_me_by_id_and_clears_with_empty_text(client, world):
    item = add(client)
    assert run(world.app, "task_manager_update", {"item": item, "tag": "me"})[0]
    assert store_of(world.app).item(item)[item_owner.TAG_COLUMN] == "ses_new"
    assert run(world.app, "task_manager_update", {"item": item, "tag": "ses_other"})[0]
    assert store_of(world.app).item(item)[item_owner.TAG_COLUMN] == "ses_other"
    assert run(world.app, "task_manager_update", {"item": item, "tag": ""})[0] and store_of(world.app).item(item)[item_owner.TAG_COLUMN] == ""
    ok, error = run(world.app, "task_manager_update", {"item": item, "tag": "remote:peer-x"})
    assert not ok and "this computer" in error


def test_the_batch_update_op_sets_a_tag(client, world):
    item = add(client)
    ok, body = run(world.app, "task_manager_batch_run", {"list_id": "12", "ops": [{"op": "update", "item_id": item, "tag": "ses_other"}]})
    assert ok and body["applied"] == 1 and store_of(world.app).item(item)[item_owner.TAG_COLUMN] == "ses_other"


def test_a_tag_survives_the_tick_while_the_owner_does_not(client, world):
    item = add(client)
    store_of(world.app).mark_working(item, "ses_old")
    tag(client, item, "ses_other")
    client.patch(f"{BASE}/items/{item}", json={"approved": True})
    done = store_of(world.app).item(item)
    assert done[item_owner.TAG_COLUMN] == "ses_other" and done[item_owner.COLUMN] == ""


def test_the_aggregate_names_a_live_tagged_agent(client, world):
    item = add(client)
    tag(client, item, "ses_other")
    items = [i for g in client.get(f"{BASE}/aggregate").json()["groups"] for i in g["items"]]
    assert next(i for i in items if i["id"] == item)["tagged_by"] == "ses_other"


def test_a_tagged_item_is_told_to_its_agent_ahead_of_its_owner(client, world, pasted):
    mine, plain = add(client, "tagged"), add(client, "plain")
    told_once(client)
    store_of(world.app).mark_working(mine, "ses_old")
    tag(client, mine, "ses_new")
    joe_reply(client, mine)
    joe_reply(client, plain)
    result = client.post(SEND, json={"lists": ["12"]}).json()["results"][0]
    parts = {p["target"]: p["items"] for p in result["parts"]}
    assert parts == {"ses_new": [mine], "ses_old": [plain]}
    assert f"(item ids {mine})" in next(text for target, text in pasted if target == "ses_new")


def test_a_tag_on_another_projects_agent_is_still_told_to_it(client, world, pasted):
    item = add(client)
    told_once(client)
    tag(client, item, "ses_other")
    joe_reply(client, item)
    result = client.post(SEND, json={"lists": ["12"]}).json()["results"][0]
    assert result["status"] == "sent" and pasted[-1][0] == "ses_other" and f"(item ids {item})" in pasted[-1][1]


def test_an_asleep_tagged_agent_is_woken_and_then_told_as_a_normal_send(client, world, pasted):
    item = add(client)
    told_once(client)
    world.sleeper()
    from src.cplugs.huddle.roles import tags
    tags.set_tag(store_of(world.app), item, SLEEPER)
    joe_reply(client, item)
    result = client.post(SEND, json={"lists": ["12"]}).json()["results"][0]
    assert world.woken == [SLEEPER] and result["status"] == "sent"
    target, text = pasted[-1]
    assert target == SLEEPER and f"(item ids {item})" in text and "task_manager_changes" in text
    assert store_of(world.app).item(item)[item_owner.TAG_COLUMN] == SLEEPER


def test_a_gone_tagged_agent_hands_the_task_to_the_lead_in_one_step(client, world, pasted):
    item = add(client)
    told_once(client)
    assert client.put(f"{BASE}/lists/12/lead", json={"session": "ses_new"}).status_code == 200
    from src.cplugs.huddle.roles import tags
    tags.set_tag(store_of(world.app), item, "ses_ghost")
    store_of(world.app).mark_working(item, "ses_ghost")
    joe_reply(client, item)
    result = client.post(SEND, json={"lists": ["12"]}).json()["results"][0]
    moved = store_of(world.app).item(item)
    assert (moved[item_owner.COLUMN], moved[item_owner.TAG_COLUMN]) == ("ses_new", "") and moved["status"] != "working"
    assert result["status"] == "sent" and pasted[-1][0] == "ses_new"
    with closing(store_of(world.app)._connect(False)) as conn:
        last = lineage.for_item(conn, item)[-1]
    assert (last["by"], last["detail"]) == ("carnivore", "tag_gone")


def test_a_gone_tagged_agent_with_no_lead_becomes_one_carnivore_question_and_no_toast(client, world, pasted, monkeypatch):
    monkeypatch.setattr(service, "surface_question", lambda *a, **k: pytest.fail("a Carnivore question raises no toast"))
    item = add(client)
    told_once(client)
    from src.cplugs.huddle.roles import tags
    tags.set_tag(store_of(world.app), item, "ses_ghost")
    joe_reply(client, item)
    result = client.post(SEND, json={"lists": ["12"]}).json()["results"][0]
    assert result["status"] == "sent" and pasted[-1][0] == "ses_old"
    questions = [m for m in store_of(world.app).item(item)["thread"] if m["kind"] == "question"]
    assert [(m["author_key"], m["category"]) for m in questions] == [("carnivore", "session_gone")]
    from src.cplugs.huddle.roles import tag_send
    assert tag_send._ask_for_gone(store_of(world.app), [item], ask.SESSION_GONE) == []
    assert len([m for m in store_of(world.app).item(item)["thread"] if m["kind"] == "question"]) == 1


def test_an_asleep_agent_that_will_not_wake_is_a_wake_failed_question(client, world):
    item = add(client)
    told_once(client)
    world.sleeper()
    world.refuse_wake = True
    from src.cplugs.huddle.roles import tags
    tags.set_tag(store_of(world.app), item, SLEEPER)
    joe_reply(client, item)
    client.post(SEND, json={"lists": ["12"]})
    assert [m["category"] for m in store_of(world.app).item(item)["thread"] if m["kind"] == "question"] == ["wake_failed"]


def stall_question(world, item: int) -> int:
    ask.carnivore_ask(store_of(world.app), item, category=ask.STALL, context="idle for 90 min", options=ask.STALL_OPTIONS)
    return next(m["id"] for m in store_of(world.app).item(item)["thread"] if m["kind"] == "question" and not m["answered"])


def answer(client, message_id: int, choice: str) -> dict:
    return client.post(f"{BASE}/questions/{message_id}/answer", json={"answers": {"q1": {"choice": choice}}}).json()


def test_unstick_on_a_stall_wakes_the_owning_session_and_tells_it_once(client, world, pasted):
    item = add(client)
    told_once(client)
    world.sleeper()
    store_of(world.app).mark_working(item, SLEEPER)
    store_of(world.app).update(item, actor="claude", state="open")
    before = len(pasted)
    body = answer(client, stall_question(world, item), "unstick")
    assert "carnivore" not in body and world.woken == [SLEEPER]
    assert len(pasted) == before + 1 and pasted[-1][0] == SLEEPER and "task_manager_changes" in pasted[-1][1]


@pytest.mark.parametrize("choice", ["cancel", "park"])
def test_cancel_and_park_send_no_tell_and_wake_nobody(client, world, pasted, choice):
    item = add(client)
    told_once(client)
    world.sleeper()
    store_of(world.app).mark_working(item, SLEEPER)
    before = len(pasted)
    answer(client, stall_question(world, item), choice)
    assert world.woken == [] and len(pasted) == before


def test_unstick_on_a_gone_tag_clears_it_wakes_the_projects_newest_sleeper_and_tells_it(client, world, pasted):
    item = add(client)
    told_once(client)
    from src.cplugs.huddle.roles import tags
    tags.set_tag(store_of(world.app), item, "ses_ghost")
    joe_reply(client, item)
    client.post(SEND, json={"lists": ["12"]})
    world.sleeper()
    question = next(m["id"] for m in store_of(world.app).item(item)["thread"] if m["kind"] == "question" and not m["answered"])
    answer(client, question, "unstick")
    assert store_of(world.app).item(item)[item_owner.TAG_COLUMN] == "" and world.woken == [SLEEPER]
    assert pasted[-1][0] == SLEEPER
