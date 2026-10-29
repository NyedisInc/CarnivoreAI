
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from src.core.mcp import beast_mode, messaging_tools, pending, route_adapters, session_target, tools
from src.core.mcp.caller import AgentCaller
from src.core.messaging import contract, store
from tests.python.beast_mode.grid import arm as arm_beast  # noqa: E402

from .conftest import CONV, JOE, OTHER_CONV, UUID_A

NEW_CONV = "any;-;+15555550177"
NUMBER_CONV = "any;-;+15555550188"
CALLER = AgentCaller("ses_a", "cloude_ledgerbot", "ses_a")


@pytest.fixture
def armed(world, monkeypatch):
    inbox = pending.PendingActions()
    monkeypatch.setattr(pending, "_store", inbox)
    arm_beast(monkeypatch, lambda: False)
    monkeypatch.setattr(route_adapters, "route_request",
                        lambda manager: SimpleNamespace(app=world.app, scope={}, headers={}, query_params={}))
    world.provider.listed += [contract.ConversationEntry(NEW_CONV, "build room", (JOE, "+1"), True),
                              contract.ConversationEntry(NUMBER_CONV, "+1 (555) 555-0188", ("+1",), True)]
    world.manager.gate_waited = True
    world.inbox = inbox
    return world


def _call(world, tool, args):
    result = asyncio.run(tools.call_tool(world.manager, CALLER, tool, args))
    assert not result.get("isError"), result
    return json.loads(result["content"][0]["text"])


def _error(world, tool, args) -> str:
    result = asyncio.run(tools.call_tool(world.manager, CALLER, tool, args))
    assert result.get("isError"), result
    return result["content"][0]["text"]


def test_the_list_is_routable_only_and_never_shows_a_handle(armed):
    answer = _call(armed, "messaging_conversations_list", {})
    text = json.dumps(answer)
    assert "+1555" not in text and "any;-;" not in text and "555" not in text
    names = {c["name"] for c in answer["available"]}
    assert names == {"joe", "build room", messaging_tools.UNNAMED}
    assert answer["registered"] == [{"id": armed.conv_id, "name": "joe"}]
    joe = next(c for c in answer["available"] if c["name"] == "joe")
    assert joe["registered"] == armed.conv_id


def test_the_add_waits_with_beast_off_and_never_parks_a_handle(armed):
    ref = next(c["ref"] for c in _call(armed, "messaging_conversations_list", {})["available"]
               if c["name"] == "build room")
    answer = _call(armed, "messaging_conversation_add", {"conversation": ref})
    assert answer["status"] == "pending" and store.list_conversations() == [
        r for r in store.list_conversations() if r["id"] == armed.conv_id]
    item = armed.inbox.get(answer["id"]) if hasattr(armed.inbox, "get") else None
    shown = json.dumps(answer) + (item.args_summary if item else "")
    assert "build room" in shown and "+1555" not in shown and "any;-;" not in shown


def test_approve_registers_then_the_binding_works_end_to_end(armed, monkeypatch):
    ref = next(c["ref"] for c in _call(armed, "messaging_conversations_list", {})["available"]
               if c["name"] == "build room")
    answer = _call(armed, "messaging_conversation_add", {"conversation": ref, "label": "builds"})
    done = asyncio.run(armed.inbox.approve(answer["id"]))
    assert done.status == pending.APPROVED
    rows = {r["label"]: r["id"] for r in store.list_conversations()}
    assert "builds" in rows
    assert armed.rt.providers[armed.pid].secrets.conversations[rows["builds"]] == NEW_CONV

    class Resolver:
        def __init__(self, manager): pass
        async def resolve(self, args, *, reach, tool):
            return SimpleNamespace(live=True, info=armed.manager.infos["ses_a"], tmux_name="cloude_ledgerbot")
        async def uuid_of(self, target): return UUID_A

    monkeypatch.setattr(session_target, "TargetResolver", Resolver)

    async def listed():
        return list(armed.manager.infos.values())

    for row in armed.manager.infos.values():
        row.host_key = None
    armed.manager.list_session_infos = listed
    bound = _call(armed, "messaging_binding_create", {"target": "cloude_ledgerbot", "conversation": rows["builds"],
                                                      "direction": "both"})
    assert bound["status"] == "pending"
    asyncio.run(armed.inbox.approve(bound["id"]))
    assert [b["conversation_id"] for b in store.list_bindings(session_uuid=UUID_A)] == [rows["builds"]]


def test_a_conversation_that_stopped_being_routable_refuses_after_approval(armed):
    ref = next(c["ref"] for c in _call(armed, "messaging_conversations_list", {})["available"]
               if c["name"] == "build room")
    answer = _call(armed, "messaging_conversation_add", {"conversation": ref})
    armed.provider.listed = [e for e in armed.provider.listed if e.conversation != NEW_CONV]
    done = asyncio.run(armed.inbox.approve(answer["id"]))
    assert "not_routable" in json.dumps(done.result)
    assert [r["label"] for r in store.list_conversations()] == ["joe"]


def test_an_unknown_ref_an_unroutable_one_and_an_unnamed_one_without_a_label_are_refused(armed):
    assert "not_routable" in _error(armed, "messaging_conversation_add", {"conversation": "0" * 16})
    listed = _call(armed, "messaging_conversations_list", {})["available"]
    unnamed = next(c["ref"] for c in listed if c["name"] == messaging_tools.UNNAMED)
    assert "label" in _error(armed, "messaging_conversation_add", {"conversation": unnamed})
