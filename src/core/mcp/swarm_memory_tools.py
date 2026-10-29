
from __future__ import annotations

from typing import Any

from src.core.mcp import route_adapters as ra


async def _cleanup(call: ra.Call) -> Any:
    return await call.route(call.request)


def _summary(_args: dict, _target: Any) -> str:
    return "wake every project agent to prune its and its children's memory by the memory bar and report kept and deleted"


SPECS = (
    ra.RouteTool(
        name="swarm_memory_cleanup", route="src.api.swarm_routes:post_memory_cleanup", gate=ra.ACT,
        description="The one-time memory cleanup: every live project agent is woken to delete its own and its children's facts "
                    "that fail the memory bar (in code or docs, stale, duplicate, not a lasting rule) and posts \"kept N, deleted M\". "
                    "Asks the owner unless Beast Mode is armed.",
        invoke=_cleanup, summary=_summary, example={},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
