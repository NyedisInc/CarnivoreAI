
from __future__ import annotations

from typing import Any

from src.core.approvals import beast_policy
from src.core.mcp import route_adapters as ra
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok


async def _status(call: ra.Call) -> Any:
    return {**await call.route(), "grid": beast_policy.current().status()}


async def beastmode_off(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api.beast_mode_routes import BeastSetting, set_beast_mode

    if args:
        raise ToolError("beastmode_off takes no arguments; it can only turn Beast Mode off")
    return _ok(await set_beast_mode(BeastSetting(enabled=False), f"mcp:{caller.tmux_name}"))


SPECS = (
    ra.RouteTool(
        name="beastmode_status", route="src.api.beast_mode_routes:get_beast_mode", gate=ra.READ,
        description="Read whether the owner has armed Beast Mode, whether it also answers session permission prompts (prompts), when it switches "
                    "itself off (until, null for never), and the grid: which prompt kinds Carnivore handles with Beast off and with Beast on, which "
                    "are handled now, and what always asks the owner. Agents can turn it off (beastmode_off), never on. Read only.",
        invoke=_status, example={},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
WRITE_TOOLS["beastmode_off"] = (
    "Turn Beast Mode OFF (writes and prompts then wait for the owner again, unless the owner ticked them under beast off: this does "
    "not clear those boxes, only the owner can untick them). Runs at once. No tool can turn it on: only the owner arms it, in the app.",
    {}, [], beastmode_off,
)
