
from __future__ import annotations

from typing import Any

from src.core.mcp import route_adapters as ra


async def _status(call: ra.Call) -> Any:
    return await call.route()


async def _preview(call: ra.Call) -> Any:
    from src.api import retention_routes

    return await call.route(retention_routes.RetentionRunRequest(dry_run=True))


async def _run(call: ra.Call) -> Any:
    from src.api import retention_routes

    return await call.route(retention_routes.RetentionRunRequest(dry_run=False))


SPECS = (
    ra.RouteTool(
        name="retention_status", route="src.api.retention_routes:get_retention_status", gate=ra.READ,
        description="Carnivore's housekeeping: whether it is on, the keep counts and log cap, whether a run is in progress, "
                    "and the last real run's report (each old db backup, rollback bundle or log it moved to the backup "
                    "drive, or why it did not). last_run is null until one ran.",
        invoke=_status, example={},
    ),
    ra.RouteTool(
        name="retention_preview", route="src.api.retention_routes:run_retention_now", gate=ra.ARRANGE,
        description="Dry run of the housekeeping now: lists what a run would move to the backup drive and whether the drive "
                    "is ready. Changes nothing.",
        invoke=_preview, example={},
    ),
    ra.RouteTool(
        name="retention_run", route="src.api.retention_routes:run_retention_now", gate=ra.ACT,
        description="Run the housekeeping now: older database backups, rollback app bundles and app logs go to the backup "
                    "drive, each removed from the Mac only after a verified copy. With the drive missing nothing moves. "
                    "Needs the owner's approval.",
        invoke=_run, summary=lambda _args, _target: "move old backups, rollback bundles and logs to the backup drive",
        example={},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
