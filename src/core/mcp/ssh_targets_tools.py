
from __future__ import annotations

from typing import Any

from src.core.mcp import route_adapters as ra


def _list(call: ra.Call) -> Any:
    return call.route()


SPECS = (
    ra.RouteTool(
        name="ssh_targets_list", route="src.api.pack_ssh_target_routes:list_targets", gate=ra.READ,
        description="List the computers reached by plain ssh (no carnivore there) that can take command jobs: each one's state (taking work, off, host key "
                    "not confirmed, did not answer), abilities, load and live jobs. Writes nothing; only the owner turns one on, in the app.",
        invoke=_list, example={},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
