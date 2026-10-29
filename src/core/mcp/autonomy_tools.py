
from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from src.core.mcp import route_adapters as ra
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok

READ_TOOLS: dict = {}
UNGATED_WRITES: set = set()


async def autonomy_off(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api.autonomy_routes import post_stand_down

    if args:
        raise ToolError("autonomy_off takes no arguments")
    answer = await post_stand_down(ra.route_request(manager))
    if isinstance(answer, JSONResponse):
        raise ToolError("stand down failed on every step: " + answer.body.decode())
    return _ok(answer.model_dump())


WRITE_TOOLS = {
    "autonomy_off": (
        "Stand down (autonomy off): turn Beast Mode off, turn the Swarm off and pause the scheduler, in one call. Alerts and notifications "
        "are untouched, agents and their memory are kept. Runs at once. Turning them back on is the owner's.",
        {}, [], autonomy_off,
    ),
}
