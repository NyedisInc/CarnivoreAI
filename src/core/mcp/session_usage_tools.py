
from __future__ import annotations

from typing import Any

from src.core.mcp import route_adapters as ra
from src.core.mcp.common import ToolError
from src.core.session_usage import rollup


async def _usage(call: ra.Call) -> Any:
    days = call.args.get("days", rollup.DEFAULT_DAYS)
    if isinstance(days, bool) or not isinstance(days, int) or not rollup.MIN_DAYS <= days <= rollup.MAX_DAYS:
        raise ToolError(f"days must be a whole number from {rollup.MIN_DAYS} to {rollup.MAX_DAYS}")
    return await call.route(days=days)


SPECS = (
    ra.RouteTool(
        name="session_usage_get", route="src.api.session_usage_routes:sessions_usage", gate=ra.READ,
        description="Which sessions were worked most: per session the seconds worked, active days and last worked time over "
                    "the last days (default 30, max 90). Sessions with no measured activity are absent, never zero; "
                    "state no_stats means nothing was ever measured.",
        properties={"days": {"type": "integer", "minimum": rollup.MIN_DAYS, "maximum": rollup.MAX_DAYS}},
        invoke=_usage, example={"days": 7},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
