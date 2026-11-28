
from __future__ import annotations

from typing import Any

from src.core.mcp import route_adapters as ra


def _stats(call: ra.Call) -> Any:
    return call.route(int(call.args.get("days", 7)))


def _activity(call: ra.Call) -> Any:
    return call.route(
        days=int(call.args.get("days", 7)),
        limit=int(call.args.get("limit", 100)),
        include_peers=bool(call.args.get("include_peers", True)),
    )


SPECS = (
    ra.RouteTool(
        name="delegate_stats", route="src.api.pack_jobs_metrics_routes:get_metrics", gate=ra.READ,
        description="How much heavy work stayed on this computer: p3 (misses over 7 days), r3 (share of heavy minutes that ran on another "
                    "computer) and this computer's last 24 hours of load. Writes nothing.",
        properties={"days": {"type": "integer", "minimum": 1, "maximum": 30, "description": "the r3 window in days, default 7"}},
        invoke=_stats, example={"days": 7},
    ),
    ra.RouteTool(
        name="pack_load_get", route="src.api.pack_jobs_metrics_routes:get_load_report", gate=ra.READ,
        description="Pack-wide CPU and RAM utilization report: live per-machine and aggregate CPU/RAM headroom, 24h/7d utilization history "
                    "and idle-while-peer-pegged waste minutes, per-project mirror overhead vs run time, guard decision funnel, and learned "
                    "command resource profiles. Writes nothing.",
        properties={"days": {"type": "integer", "minimum": 1, "maximum": 30, "description": "report window in days, default 7"}},
        invoke=_stats, example={"days": 7},
    ),
    ra.RouteTool(
        name="pack_activity_get", route="src.api.pack_jobs_metrics_routes:get_pack_activity", gate=ra.READ,
        description="Live distribution and historical log of all agents and delegated jobs across every computer in the Pack, showing which "
                    "computer each ran on, when it spun up, who spun it up, and peer-to-peer fan-out. Writes nothing.",
        properties={
            "days": {"type": "integer", "minimum": 1, "maximum": 30, "description": "history window in days, default 7"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500, "description": "max activity items, default 100"},
            "include_peers": {"type": "boolean", "description": "query connected peers for peer-to-peer jobs, default true"},
        },
        invoke=_activity, example={"days": 7, "limit": 50},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
