
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

import pytest

from src.core.mcp import beast_mode, pane_only, pending, tools
from src.core.mcp.approvals import call_context, runtime as approval_runtime
from src.core.mcp.caller import AgentCaller
from src.core.mcp.registry import gates
from src.core.swarm.cards import port as card_port
from tests.python.swarm.cards.test_card_enforcement import caller, world  # noqa: F401

EXPECTED = {
    **{name: gates.PANE_ONLY for name in (
        "swarm_report", "swarm_accept_report", "swarm_propose_naming", "swarm_suggest", "swarm_remember", "swarm_forget", "swarm_ask", "swarm_answer",
        "swarm_pass", "swarm_promote", "swarm_say", "swarm_conflict", "swarm_card_create", "swarm_card_start", "swarm_card_handoff",
        "swarm_card_finish", "swarm_card_release", "swarm_card_reorder", "swarm_card_deal", "swarm_card_auto_promote",
        "swarm_card_queue", "swarm_card_verdict", "messaging_send")},
    "swarm_card_grant": gates.ACT, "swarm_card_pace": gates.ACT, "session_send_message": gates.ACT,
    "swarm_switch_off": gates.AGENT_DIRECT, "autonomy_off": gates.AGENT_DIRECT,
    "approval_wait": gates.READ,
}
TOKEN = AgentCaller(session_id="mcp-token:7", tmux_name="mcp-token:7", current_session_id="mcp-token:7", token_name="desk")


def _run(view: Any, who: AgentCaller, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    out = asyncio.run(tools.call_tool(view, who, name, args))
    text = out["content"][0]["text"]
    try:
        body: Any = json.loads(text)
    except ValueError:
        body = text
    return {"error": bool(out.get("isError")), "body": body}


@pytest.fixture
def inbox(monkeypatch):
    store = pending.PendingActions()
    monkeypatch.setattr(pending, "_store", store)
    monkeypatch.setattr(beast_mode, "approval_skip", lambda action, **kw: False)

    async def no_pin(manager: Any, target_id: str) -> tuple:
        return None, ""

    monkeypatch.setattr(approval_runtime, "pin", no_pin)
    return store


def test_no_write_is_undeclared_and_each_of_the_28_has_its_class():
    classes = gates.gate_classes()
    assert gates.UNDECLARED_WRITES == frozenset()
    assert [n for n, c in classes.items() if c == gates.UNDECLARED] == []
    assert {n: classes[n] for n in EXPECTED} == EXPECTED
    assert set(pane_only.STANDING) <= tools.WRITE_TOOLS
    others = call_context.GATED_TOOLS | tools._UNGATED_WRITES | beast_mode.ALWAYS_WAITS | tools.DIRECT_WRITES
    assert not set(pane_only.STANDING) & others and not tools.DIRECT_WRITES & (call_context.GATED_TOOLS | tools._UNGATED_WRITES)


def test_a_capacity_write_parks_as_a_pending_act_and_runs_only_once_the_owner_approves(world, inbox):
    w = world
    w.view.gate_waited = True
    pace = lambda: asyncio.run(card_port.get().policy_read("rules", {"list_keys": ["16"]}))["rules"]["16"]["pace"]  # noqa: E731
    assert pace() == "normal"
    out = _run(w.view, caller("boss"), "swarm_card_pace", {"project_id": 16, "pace": "asap"})
    assert not out["error"] and out["body"]["status"] == "pending" and out["body"]["id"].startswith("act_")
    assert pace() == "normal"
    item = inbox.get(out["body"]["id"])
    assert item.action == "swarm_card_pace" and item.args == {"project_id": 16, "pace": "asap"}
    asyncio.run(inbox.approve(item.id))
    assert json.loads(item.result["content"][0]["text"])["rules"]["pace"] == "asap" and pace() == "asap"
    refused = _run(w.view, caller("boss"), "swarm_card_pace", {"project_id": 17, "pace": "asap"})
    assert refused["error"] and "not_allowed" in refused["body"] and len(inbox.list()) == 0


def test_a_swarm_pane_only_tool_refuses_a_token_and_a_plain_pane_and_runs_for_a_swarm_agent(world, inbox):
    w = world
    args = {"title": "t", "summary": "a plain line", "project_id": 16}
    by_token = _run(w.view, TOKEN, "swarm_card_create", args)
    assert by_token["error"] and by_token["body"].startswith("not_a_swarm_agent: swarm_card_create")
    assert inbox.list() == []
    plain = AgentCaller(session_id="ses_plain", tmux_name="cloude_plain", current_session_id="ses_plain")
    by_plain = _run(w.view, plain, "swarm_card_create", args)
    assert by_plain["error"] and by_plain["body"].startswith("not_a_swarm_agent: swarm_card_create")
    by_agent = _run(w.view, caller("boss"), "swarm_card_create", args)
    assert not by_agent["error"] and by_agent["body"]["card"]["id"] > 0
    assert asyncio.run(pane_only.refusal(w.view, TOKEN, "messaging_send")).startswith("messaging_send runs only from a session")
    assert asyncio.run(pane_only.refusal(w.view, plain, "messaging_send")) is None
    assert asyncio.run(pane_only.refusal(w.view, TOKEN, "sessions_list")) is None


def test_approval_wait_is_a_read_with_the_read_only_hint():
    assert gates.gate_class("approval_wait") == gates.READ and "approval_wait" not in tools.WRITE_TOOLS
    reader = AgentCaller(session_id="mcp-token:8", tmux_name="mcp-token:8", current_session_id="mcp-token:8", token_name="r", scope="read")
    listed = {t["name"]: t for t in tools.tool_definitions(reader)}
    assert listed["approval_wait"].get("annotations") == {"readOnlyHint": True}
    assert "session_stop" not in listed
