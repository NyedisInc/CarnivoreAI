
from __future__ import annotations

from typing import Any

from src.core.mcp import route_adapters as ra


def _stats(call: ra.Call) -> Any:
    return call.route(int(call.args.get("days", 7)))


SPECS = (
    ra.RouteTool(
        name="delegate_stats", route="src.api.pack_jobs_metrics_routes:get_metrics", gate=ra.READ,
        description="How much heavy work stayed on this computer: p3 (misses over 7 days), r3 (share of heavy minutes that ran on another "
                    "computer) and this computer's last 24 hours of load. Writes nothing.",
        properties={"days": {"type": "integer", "minimum": 1, "maximum": 30, "description": "the r3 window in days, default 7"}},
        invoke=_stats, example={"days": 7},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
