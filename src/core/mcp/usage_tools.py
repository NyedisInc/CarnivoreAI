
from __future__ import annotations

from typing import Any

from src.core.mcp import route_adapters as ra
from src.core.mcp.common import ToolError
from src.core.mcp_usage import report


async def _usage(call: ra.Call) -> Any:
    days = call.args.get("days", report.DEFAULT_DAYS)
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= report.MAX_DAYS:
        raise ToolError(f"days must be a whole number from 1 to {report.MAX_DAYS}")
    answer = await call.route(days=days)
    rows = answer.get("tools") if isinstance(answer, dict) else None
    if isinstance(rows, list):
        answer = {**answer, "tools": [r for r in rows if not (isinstance(r, dict) and r.get("registered") and not r.get("total"))]}
    return answer


SPECS = (
    ra.RouteTool(
        name="mcp_usage", route="src.api.mcp_usage_routes:get_mcp_usage", gate=ra.READ,
        description="How often each MCP tool was called over the last days (default 30, max 90): per tool its total, "
                    "calls by caller kind and by outcome, and the last day it was called. zero_call_tools names the "
                    "tools nobody called. old_names: each retired name still accepted, its use "
                    "in the window and the last 7 days, by via. Counts only.",
        properties={"days": {"type": "integer", "minimum": 1, "maximum": report.MAX_DAYS}},
        invoke=_usage, example={"days": 7},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
