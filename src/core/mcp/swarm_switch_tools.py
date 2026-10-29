
from __future__ import annotations

from typing import Any

from src.core.mcp import route_adapters as ra
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok


def _status(call: ra.Call) -> Any:
    return call.route()


async def _turn_on(call: ra.Call) -> Any:
    from src.api.swarm_switch_routes import SwarmSwitchSetting

    return await call.route(SwarmSwitchSetting(enabled=True), call.request)


def _on_summary(_args: dict, _target: Any) -> str:
    return "turn the swarm back on for this whole computer (wakes, sweeps and memory commits resume)"


async def swarm_switch_off(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api.swarm_switch_routes import SwarmSwitchSetting, put_swarm_switch

    if args:
        raise ToolError("swarm_switch_off takes no arguments; it can only turn the swarm off")
    return _ok(await put_swarm_switch(SwarmSwitchSetting(enabled=False), ra.route_request(manager)))


SPECS = (
    ra.RouteTool(
        name="swarm_switch_status", route="src.api.swarm_switch_routes:get_swarm_switch", gate=ra.READ,
        description="Read whether the Swarm runs on this computer (enabled). While it is off no agent wakes or spawns, no Swarm "
                    "sweep or memory commit runs and the other swarm_* tools are hidden; agents and their memory are kept.",
        invoke=_status, example={},
    ),
    ra.RouteTool(
        name="swarm_switch_on", route="src.api.swarm_switch_routes:put_swarm_switch", gate=ra.ACT,
        description="Turn the Swarm back on for this whole computer. Asks the owner unless Beast Mode is armed.",
        invoke=_turn_on, summary=_on_summary, example={},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
WRITE_TOOLS["swarm_switch_off"] = (
    "Turn the Swarm OFF for this whole computer: no agent wakes or spawns, no Swarm sweep or memory commit runs. Agents and "
    "their memory are kept. Runs at once. Turning it back on (swarm_switch_on) needs the owner's approval.",
    {}, [], swarm_switch_off,
)
