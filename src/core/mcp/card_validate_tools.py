
from __future__ import annotations

from typing import Any, Dict

from src.core.mcp import card_tools
from src.core.mcp.caller import AgentCaller
from src.core.swarm.cards import validate


async def swarm_card_verdict(manager: Any, caller: AgentCaller, args: dict) -> dict:
    async def work() -> Any:
        full = card_tools._detail(args)
        card = await validate.verdict(manager, caller, args)
        return {"card": card if full else card_tools.lean_card(card)}

    return await card_tools._guard(work())


WRITE_TOOLS: frozenset = frozenset({"swarm_card_verdict"})

TOOLS: Dict[str, Any] = {
    "swarm_card_verdict": (
        "End the validation you were ordered to run on a card: verdict pass or fail, and the proof, what you ran and what you saw, verbatim. "
        "Only the agent validating that card may call it. A pass does not move the card to Done.",
        {"card_id": {"type": "integer", "minimum": 1}, "verdict": {"type": "string", "enum": ["pass", "fail"]},
         "proof": {"type": "string", "minLength": 1, "maxLength": validate.MAX_PROOF_CHARS}, **card_tools._DETAIL},
        ["card_id", "verdict", "proof"], swarm_card_verdict),
}
