
from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_aw_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_aw_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.api import session_bookmark_routes
from src.core.mcp import beast_mode, bookmark_tools, pending, route_adapters, tools, write_tools
from src.core.mcp.caller import AgentCaller
from tests.python.beast_mode.grid import arm as arm_beast  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
PROMISE = re.compile(r"\balways waits?\b", re.IGNORECASE)
DECLARATION = re.compile(r"^\s*ALWAYS_WAITS\s*(?::[^=]*)?=", re.MULTILINE)


def _descriptions() -> dict:
    return {name: row[0] for name, row in tools._TOOLS.items()}


@pytest.fixture
def armed(monkeypatch):
    store = pending.PendingActions()
    monkeypatch.setattr(pending, "_store", store)
    arm_beast(monkeypatch, lambda: True)
    return store


def _status(result: dict) -> dict:
    assert not result.get("isError"), result
    return json.loads(result["content"][0]["text"])


def test_the_set_is_declared_in_exactly_one_place():
    found = [str(p.relative_to(REPO)) for p in (REPO / "src").rglob("*.py") if DECLARATION.search(p.read_text())]
    assert found == ["src/core/mcp/beast_mode.py"], found


def test_every_tool_promising_to_wait_is_in_the_set_and_every_member_promises_it():
    described = _descriptions()
    promised = {name for name, text in described.items() if PROMISE.search(text)}
    assert promised - beast_mode.ALWAYS_WAITS == set(), "a tool says it always waits but Beast could skip it"
    assert beast_mode.ALWAYS_WAITS - set(described) == set(), "a member of ALWAYS_WAITS is not a registered tool"
    assert beast_mode.ALWAYS_WAITS - promised == set(), "a member of ALWAYS_WAITS does not tell the caller it waits"


def test_no_member_is_beast_eligible_even_if_added_to_the_allowlist(armed, monkeypatch):
    assert beast_mode.ALWAYS_WAITS.isdisjoint(beast_mode.AGENT_ACTIONS)
    monkeypatch.setattr(beast_mode, "AGENT_ACTIONS", beast_mode.AGENT_ACTIONS | beast_mode.ALWAYS_WAITS)
    for action in beast_mode.ALWAYS_WAITS:
        assert not beast_mode.eligible_action(action), action
        assert not beast_mode.approval_skip(action), action


@pytest.mark.parametrize("action", sorted(beast_mode.ALWAYS_WAITS))
def test_each_handler_parks_its_own_action(action):
    handler = tools._TOOLS[action][3]
    source = inspect.getsource(inspect.getmodule(handler))
    adapter_acts = {s.name for m in tools._ROUTE_MODULES for s in getattr(m, "SPECS", ()) if s.gate == route_adapters.ACT}
    assert "park(" in source and (f'"{action}"' in source or action in adapter_acts), f"{action}'s module never parks it"


@pytest.mark.parametrize("action", sorted(beast_mode.ALWAYS_WAITS))
def test_armed_beast_leaves_it_pending_and_only_the_owner_approve_runs_it(armed, action):
    ran = []

    async def run(approved: bool) -> dict:
        ran.append(approved)
        return {"content": [{"type": "text", "text": "{\"ok\": true}"}]}

    manager = SimpleNamespace(gate_waited=True)
    caller = AgentCaller("ses_orch", "cloude_orch", "ses_orch")
    answer = _status(asyncio.run(write_tools.park(manager, caller, "", "", action, action, {"n": 1}, run,
                                                  dedupe_key=action)))
    assert answer["status"] == "pending" and ran == []
    assert asyncio.run(beast_mode.approve_pending()) == 0 and ran == []
    item = asyncio.run(armed.approve(answer["id"]))
    assert ran == [True] and item.status == pending.APPROVED and item.approval_source != "approved by beast mode"


@pytest.mark.parametrize("tool,args,route", [
    ("bookmark_rewind", {"bookmark": 2, "confirm": True, "huddle_item": 81}, "rewind_bookmark"),
])
def test_bookmark_tools_through_the_dispatcher_wait_for_the_owner_under_beast(armed, monkeypatch, tool, args, route):
    """End to end from ``call_tool``, with the unknown-to-the-handler ``huddle_item`` the live call carried."""
    called = []

    async def fake_bookmark(bookmark_id):
        return SimpleNamespace(label="branch before charlie", snippet="")

    async def fake_route(request, bookmark_id, *rest):
        called.append(bookmark_id)
        return SimpleNamespace(model_dump=lambda: {"done": True}, label="x", claude_session_uuid="c",
                               session={"id": "ses_new"}, lineage_recorded=True)

    monkeypatch.setattr(session_bookmark_routes, "_bookmark", fake_bookmark)
    monkeypatch.setattr(session_bookmark_routes, route, fake_route)
    monkeypatch.setattr(bookmark_tools, "_request", lambda manager: SimpleNamespace(app=None))
    manager = SimpleNamespace(gate_waited=True, app=object())
    caller = AgentCaller("ses_55975c1b", "carnivore_orchestrator", "ses_55975c1b")

    answer = _status(asyncio.run(tools.call_tool(manager, caller, tool, args)))
    assert answer["status"] == "pending" and called == []
    assert asyncio.run(beast_mode.approve_pending()) == 0 and called == []
    asyncio.run(armed.approve(answer["id"]))
    assert called == [2]
