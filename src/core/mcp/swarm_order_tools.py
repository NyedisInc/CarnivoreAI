
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.mcp.write_tools import _via_route
from src.core.swarm.node_order import MAX_KEYS, TIERS


async def swarm_node_order(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import swarm_node_order_routes

    if args:
        raise ToolError("swarm_node_order takes no arguments")
    return _ok(await _via_route(swarm_node_order_routes.get_node_order()))


async def swarm_set_node_order(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import swarm_node_order_routes

    if set(args) - {"tier", "keys"} or "tier" not in args or "keys" not in args:
        raise ToolError("swarm_set_node_order takes tier and keys")
    try:
        body = swarm_node_order_routes.NodeOrderWrite(tier=args["tier"], keys=args["keys"])
    except ValidationError:
        raise ToolError(f"tier must be one of {', '.join(TIERS)} and keys a list of at most {MAX_KEYS} node keys") from None
    return _ok(await _via_route(swarm_node_order_routes.put_node_order(body)))


_KEYS_SCHEMA = {"type": "array", "maxItems": MAX_KEYS, "items": {"type": "string"},
                "description": "node keys in order, first square first: agent:<id>, company:<id>, project:<id> or session:<session_uuid>"}

READ_TOOLS: dict = {
    "swarm_node_order": (
        "The owner's hand-set order of the Swarm squares in each tier (companies, projects, agents), as node keys "
        "(agent:<id>, company:<id>, project:<id>, session:<session_uuid>). An empty tier draws in its computed order.",
        {}, [], swarm_node_order,
    ),
}

WRITE_TOOLS: dict = {
    "swarm_set_node_order": (
        "Replace one Swarm tier's square order, the same on every device. A node the floor does not draw keeps its "
        "place for when it comes back; a node left out draws after the listed ones. Open Swarm grids update live.",
        {"tier": {"type": "string", "enum": list(TIERS)}, "keys": _KEYS_SCHEMA}, ["tier", "keys"], swarm_set_node_order,
    ),
}
