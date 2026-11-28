
from __future__ import annotations

from typing import Any

from src.core.mcp import route_adapters as ra


def _list(call: ra.Call) -> Any:
    return call.route()


SPECS = (
    ra.RouteTool(
        name="pack_leftovers_list", route="src.api.pack_leftovers_routes:list_leftovers", gate=ra.READ,
        description="Stats this computer still holds for computers that are gone from the Pack: per computer its id, name, newest time and row counts. "
                    "known is false when no signed computer list is held. Read only; the owner clears them in the app.",
        properties={}, invoke=_list, example={},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
