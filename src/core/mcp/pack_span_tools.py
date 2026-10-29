
from __future__ import annotations

from typing import Any

from src.core.mcp import route_adapters as ra


def _refresh(call: ra.Call) -> Any:
    from src.api.pack_refresh_routes import RefreshBody

    return call.route(RefreshBody(project=call.args.get("project"), install=bool(call.args.get("install", False))))


SPECS = (
    ra.RouteTool(
        name="pack_refresh_run", route="src.api.pack_refresh_routes:pack_refresh", gate=ra.ACT,
        description="Refresh the Pack after a change lands: with project, carry that project's latest commits to its replica "
                    "computers; with install, ask every connected computer that tracks master to refresh its Carnivore install.",
        properties={"project": {"type": "string", "maxLength": 200, "description": "a project name (its replicas get the code)"},
                    "install": {"type": "boolean", "description": "also ask tracking computers to refresh their install"}},
        invoke=_refresh,
        summary=lambda args, _t: f"refresh the Pack (project {str(args.get('project') or '-')[:60]}, install {bool(args.get('install'))})",
        example={"project": "trader", "install": True},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
