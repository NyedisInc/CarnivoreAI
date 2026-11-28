
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from src.core.boot.steps import BootStep

if TYPE_CHECKING:
    from src.core.boot.context import BootContext

logger = structlog.get_logger()


async def _run(app) -> None:
    from src.api import catalog_default_installs, mods_routes
    from src.core.mods import owner_state

    request = catalog_default_installs.boot_request(app)
    try:
        await asyncio.to_thread(lambda: mods_routes._scan(request, reconcile=True))
        await catalog_default_installs.install_defaults(request)
    except Exception as exc:  # noqa: BLE001
        logger.warning("mods_boot_failed", error=type(exc).__name__)


def _start(ctx: "BootContext") -> None:
    ctx.app.state.mods_boot_task = asyncio.get_running_loop().create_task(_run(ctx.app))


def steps() -> list[BootStep]:
    return [BootStep(name="mods_boot", order=615, start=_start)]
