
from __future__ import annotations

from typing import Any

from src.core.mcp import route_adapters as ra


def _status(call: ra.Call) -> Any:
    return call.route()


def _now(call: ra.Call) -> Any:
    from src.api.pack_global_sync_routes import SyncBody

    return call.route(SyncBody(install_ids=list(call.args.get("install_ids") or [])), call.request)


SPECS = (
    ra.RouteTool(
        name="pack_global_sync_status", route="src.api.pack_global_sync_routes:get_global_sync", gate=ra.READ,
        description="The global setup sync: its settings (on, auto, per harness) and, per paired computer, the gate now (not_approved, receiver_off, "
                    "offline...) and the last pass (counts, what was held back and why). Names and counts only, never file contents.",
        properties={}, invoke=_status, example={},
    ),
    ra.RouteTool(
        name="pack_global_sync_now", route="src.api.pack_global_sync_routes:post_sync", gate=ra.ACT,
        description="Send this computer's global AI setup (rules, settings, hooks, skills, mods, plugins; secrets scrubbed) to the Pack computers that "
                    "are approved and opted in, now. Only the Pack's main computer sends; the sync must be on (the owner turns it on in the app).",
        properties={"install_ids": {"type": "array", "items": {"type": "string"}}}, invoke=_now,
        summary=lambda args, _target: "send the global setup to the Pack computers", example={},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
