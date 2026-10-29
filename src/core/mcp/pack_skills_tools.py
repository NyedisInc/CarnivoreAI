
from __future__ import annotations

from typing import Any

from src.core.mcp import route_adapters as ra


def _status(call: ra.Call) -> Any:
    return call.route(inventory=False, kick=False)


SPECS = (
    ra.RouteTool(
        name="pack_skills_status", route="src.api.pack_skills_routes:get_skills", gate=ra.READ,
        description="Pack skill sync: which computer is alpha, the generation, whether this computer holds, and per personal skill "
                    "its state (synced, held, unsynced) with one cell per computer (in sync, missing, differs, conflict with the "
                    "reason, offline, older carnivore). Names, states and digests only, never contents. Read only; alpha's "
                    "owner decides what syncs, in the app.",
        properties={}, invoke=_status, example={},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
