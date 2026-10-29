
from __future__ import annotations

import asyncio
import json

from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.core.swarm.facade import SwarmFacade
from src.cplugs.huddle import lane
from src.cplugs.huddle.swarm_port import TaskManagerSwarmPort
from tests.python.cplugs.huddle.test_task_manager_agent_lists import BASE, CALLER, world  # noqa: F401

AGENT_CALLER = AgentCaller("ses_agent", "cloude_agent", "ses_agent")


def _seed(world) -> dict:
    client = world.client
    port = TaskManagerSwarmPort(world.host.context("huddle"))
    mine = client.post(f"{BASE}/lists/12/items", json={"text": "joe task"}).json()["id"]
    card = asyncio.run(port.post_card("12", "question", "commit memory to this repo?", "commit it?", "visibility:2:ab"))
    later = client.post(f"{BASE}/lists/12/items", json={"text": "joe later"}).json()["id"]
    thread = asyncio.run(port.post_card(world.key, "question", "agent card", "agent card", "wake_refused:1"))
    return {"mine": mine, "card": card, "later": later, "thread": thread}


def _ids(items) -> set:
    return {i["id"] for i in items}


def test_the_task_manager_reads_leave_out_swarm_items_and_keep_joes(world):
    seeded = _seed(world)
    client = world.client
    body = client.get(f"{BASE}/lists/12").json()
    assert _ids(body["items"]) == {seeded["mine"], seeded["later"]}
    assert all(i["lane"] == lane.TASK_MANAGER for i in body["items"])

    groups = client.get(f"{BASE}/aggregate").json()["groups"]
    assert [g["list"] for g in groups] == ["12"]
    assert _ids(groups[0]["items"]) == {seeded["mine"], seeded["later"]}

    rows = {r["key"]: r for r in client.get(f"{BASE}/lists").json()["lists"]}
    assert rows["12"]["items"] == 2 and rows["12"]["questions"] == 0 and rows["12"]["needs_you"] == 0
    assert rows["12"]["attention"] == 0
    assert rows.get(world.key, {"items": 0})["items"] == 0

    changed = client.get(f"{BASE}/changes", params={"since": 0}).json()
    assert seeded["card"] not in _ids(changed["items"]) and {seeded["mine"], seeded["later"], seeded["thread"]} <= _ids(changed["items"])


def test_the_swarm_reads_keep_every_item(world):
    seeded = _seed(world)
    client = world.client
    whole = client.get(f"{BASE}/lists/12", params={"include_swarm": "1"}).json()
    assert _ids(whole["items"]) == {seeded["mine"], seeded["card"], seeded["later"]}
    assert _ids(client.get(f"{BASE}/lists/{world.key}").json()["items"]) == {seeded["thread"]}
    rows = {r["key"]: r for r in client.get(f"{BASE}/lists", params={"include_swarm": "1"}).json()["lists"]}
    assert rows["12"]["items"] == 3 and rows[world.key]["items"] == 1
    entries = asyncio.run(TaskManagerSwarmPort(world.host.context("huddle")).read_thread(world.key, 10))
    assert any(e.get("card") == "question" for e in entries)


def test_a_task_manager_reorder_keeps_the_hidden_card_in_its_slot(world):
    seeded = _seed(world)
    client = world.client
    body = client.get(f"{BASE}/lists/12").json()
    moved = client.put(f"{BASE}/lists/12/order", json={"ids": [seeded["later"], seeded["mine"]], "expected_revision": body["revision"]})
    assert moved.status_code == 200, moved.text
    whole = client.get(f"{BASE}/lists/12", params={"include_swarm": "1"}).json()["items"]
    assert sorted(whole, key=lambda i: i["position"])[1]["id"] == seeded["card"]
    stale = client.put(f"{BASE}/lists/12/order", json={"ids": [seeded["mine"]], "expected_revision": moved.json()["revision"]})
    assert stale.status_code == 409


def test_mcp_reads_hide_swarm_items_from_a_session_and_keep_them_for_a_swarm_agent(world, monkeypatch):
    seeded = _seed(world)

    async def thread_for_session(self, session_id):
        return "12" if session_id == AGENT_CALLER.current_session_id else None

    monkeypatch.setattr(SwarmFacade, "thread_for_session", thread_for_session)

    def listed(caller) -> set:
        answer = asyncio.run(tools.call_tool(world.manager, caller, "huddle_list", {"list": "12"}))
        assert not answer.get("isError"), answer
        return _ids(json.loads(answer["content"][0]["text"])["items"])

    assert listed(CALLER) == {seeded["mine"], seeded["later"]}
    assert listed(AGENT_CALLER) == {seeded["mine"], seeded["card"], seeded["later"]}

    changes = asyncio.run(tools.call_tool(world.manager, CALLER, "huddle_changes", {"since": 0, "list": "12"}))
    assert seeded["card"] not in _ids(json.loads(changes["content"][0]["text"])["items"])


def test_merge_order_rule():
    live = [(1, lane.TASK_MANAGER), (2, lane.SWARM), (3, lane.TASK_MANAGER)]
    assert lane.merge_order(live, [3, 1]) == [3, 2, 1]
    assert lane.merge_order(live, [2, 3, 1]) == [2, 3, 1]
    assert lane.merge_order(live, [3]) is None
    assert lane.hides_swarm("12", False) and not lane.hides_swarm("agent:7", False) and not lane.hides_swarm(None, True)
