
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, List

import pytest

from src.core.mcp import beast_mode, card_tools, write_tools
from src.core.mcp.approvals import call_context
from src.core.mcp.common import ToolError
from src.core.swarm.cards import notices, ops, port as card_port
from tests.python.swarm.cards.test_card_agent_close import held_card, world  # noqa: F401

MANAGER = SimpleNamespace(app=SimpleNamespace(state=None))


@pytest.fixture()
def told(monkeypatch) -> List[Any]:
    seen: List[Any] = []
    monkeypatch.setattr(notices, "note", lambda app_state, before, after, **_: seen.append((before["id"], after)))
    return seen


def as_agent(monkeypatch, agent_id: int) -> None:
    async def caller(manager: Any, who: Any) -> dict:
        return {"id": agent_id}
    monkeypatch.setattr(card_tools, "_caller", caller)


def events(world, card_id: int, kind: str) -> list:
    conn = world.store._connect(False)
    try:
        return [tuple(r) for r in conn.execute("SELECT by, detail FROM work_card_events WHERE item_id = ? AND kind = ?", (card_id, kind))]
    finally:
        conn.close()


def test_swarm_card_archive_runs_at_once_in_scope_and_refuses_outside_it(world, told, monkeypatch):
    card = held_card(world.store, "leftover")
    as_agent(monkeypatch, 6)
    with pytest.raises(ToolError, match="not_allowed"):
        asyncio.run(card_tools.swarm_card_archive(MANAGER, None, {"card_id": card, "reason": "stale"}))
    as_agent(monkeypatch, 9)
    with pytest.raises(ToolError, match="not_allowed"):
        asyncio.run(card_tools.swarm_card_archive(MANAGER, None, {"card_id": card, "reason": "stale"}))
    assert asyncio.run(card_port.get().card(card))["archived_at"] is None and not told

    as_agent(monkeypatch, 5)
    with pytest.raises(ToolError):
        asyncio.run(card_tools.swarm_card_archive(MANAGER, None, {"card_id": card, "reason": " "}))
    asyncio.run(card_tools.swarm_card_archive(MANAGER, None, {"card_id": card, "reason": "a leftover test card"}))
    after = asyncio.run(card_port.get().card(card))
    assert after["archived_at"] is not None and after["column"] == "todo" and after["holder"] is None
    assert events(world, card, "archived") == [("agent:5", "a leftover test card")]
    assert told == [(card, told[0][1])] and told[0][1]["archived_at"] is not None


def test_swarm_card_delete_always_waits_for_the_owner_and_refuses_outside_scope(world, told, monkeypatch):
    assert "swarm_card_delete" in beast_mode.ALWAYS_WAITS and "swarm_card_delete" in call_context.GATED_TOOLS
    parked: List[dict] = []

    async def owner_approves(manager: Any, caller: Any, target_id: str, target_tmux: str, action: str, summary: str, args: dict,
                             run: Any, **kw: Any) -> dict:
        parked.append({"action": action, "summary": summary, "args": args, **kw})
        return await run(True)

    monkeypatch.setattr(write_tools, "park", owner_approves)
    card = held_card(world.store, "leftover")
    as_agent(monkeypatch, 6)
    with pytest.raises(ToolError, match="not_allowed"):
        asyncio.run(card_tools.swarm_card_delete(MANAGER, None, {"card_id": card, "reason": "stale"}))
    assert not parked and asyncio.run(card_port.get().card(card)) is not None

    as_agent(monkeypatch, 5)
    asyncio.run(card_tools.swarm_card_delete(MANAGER, None, {"card_id": card, "reason": "a leftover test card"}))
    assert [(p["action"], p["args"], p["beast_eligible"]) for p in parked] == [("swarm_card_delete", {"card_id": card, "reason": "a leftover test card"}, False)]
    assert asyncio.run(card_port.get().card(card)) is None
    assert events(world, card, "deleted") == [("owner", "agent:5: a leftover test card")]
    assert told == [(card, None)]
    with pytest.raises(ToolError, match="not_a_card"):
        asyncio.run(card_tools.swarm_card_delete(MANAGER, None, {"card_id": card, "reason": "again"}))
