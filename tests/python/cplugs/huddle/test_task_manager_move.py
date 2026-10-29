
from __future__ import annotations

import json
from pathlib import Path

from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.cplugs.huddle import service
from tests.python.cplugs.huddle.test_task_manager_focus import add, call, client, setup  # noqa: F401

BASE = "/api/v1/cplugs/huddle"


def items(client, key: str) -> list[dict]:
    return client.get(f"{BASE}/lists/{key}").json()["items"]


def test_joe_moves_an_item_with_its_thread_note_state_and_unread(client, setup):
    first, mine = add(client, "all", "first"), add(client, "all", "move me")
    add(client, "12", "already there")
    client.post(f"{BASE}/items/{mine}/messages", json={"text": "joe reply"})
    client.patch(f"{BASE}/items/{mine}", json={"note": "for cloude", "approved": True})
    assert call(setup.manager, "task_manager_reply", {"item": mine, "text": "ok", "kind": "answer", "quote_text": "joe reply"})[0]
    assert call(setup.manager, "task_manager_reply", {"item": mine, "text": "claude reply", "notify": True})[0]
    before = next(i for i in items(client, "all") if i["id"] == mine)
    assert before["unread"] is True and before["number"] is None
    setup.published.clear()

    moved = client.post(f"{BASE}/items/{mine}/move", json={"list": "12"})
    assert moved.status_code == 200
    body = moved.json()
    assert body["list"] == "12" and body["note"] == "for cloude" and body["state"] == "done"
    assert [m["text"] for m in body["thread"] if not m.get("category")] == ["joe reply", "ok", "claude reply"] and body["unread"] is True
    assert [m["text"] for m in body["thread"] if m.get("category") == "status"] == ["status changed from open to done by the owner"]
    assert [i["id"] for i in items(client, "all")] == [first]
    assert [i["text"] for i in items(client, "12")] == ["already there", "move me"]
    assert items(client, "all")[0]["number"] == 1
    assert sorted(setup.published) == ["cplug.huddle.cards:12", "cplug.huddle.cards:all", "cplug.huddle.list:12", "cplug.huddle.list:all"]
    setup.published.clear()
    assert client.post(f"{BASE}/items/{mine}/move", json={"list": "12"}).json()["list"] == "12"
    assert setup.published == []


def test_move_refuses_an_unknown_list_a_bad_key_and_a_missing_item(client, setup):
    item = add(client, "all", "x")
    assert client.post(f"{BASE}/items/{item}/move", json={"list": "77"}).status_code == 404
    assert client.post(f"{BASE}/items/{item}/move", json={"list": "bad"}).status_code == 400
    assert client.post(f"{BASE}/items/9999/move", json={"list": "12"}).status_code == 404
    assert [i["id"] for i in items(client, "all")] == [item]


def test_claude_moves_through_the_mcp_tool_and_it_is_declared(client, setup):
    item = add(client, "all", "move this to cloude")
    manifest = json.loads((Path(service.__file__).parent / "cplug.json").read_text())
    assert "task_manager_move" in manifest["surfaces"]["mcp_tools"]
    assert any(d["name"] == "task_manager_move" for d in tools.tool_definitions())
    read_only = {d["name"] for d in tools.tool_definitions(AgentCaller("x", "x", "x", "tok", "read"))}
    assert "task_manager_move" not in read_only
    ok, moved = call(setup.manager, "task_manager_move", {"item": item, "list": "12"})
    assert ok and moved["list"] == "12" and moved["text"] == "move this to cloude"
    ok, refused = call(setup.manager, "task_manager_move", {"item": item, "list": "77"})
    assert not ok
    assert [i["id"] for i in items(client, "12")] == [item]
    changed = client.get(f"{BASE}/changes", params={"since": 0, "list": "12"}).json()
    assert [i["id"] for i in changed["items"]] == [item]
