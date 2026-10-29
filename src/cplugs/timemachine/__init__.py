
from typing import Any

import structlog

from src.cplugs.sdk import CplugDefinition, load_manifest
from src.cplugs.timemachine import constants as K
from src.cplugs.timemachine import routes, scheduler, service

logger = structlog.get_logger()


async def _start(ctx: Any) -> None:
    if not ctx.has("notify"):
        logger.info("timemachine_not_started", reason="no_notify_grant")
        return
    service.reset()
    scheduler.start(ctx)


async def _stop(ctx: Any) -> None:
    await scheduler.stop()
    resolve = getattr(ctx, "alert_resolve", None)
    if not ctx.enabled_now() and resolve is not None:
        resolve(K.ALERT_KEY)
    service.reset()


CPLUG = CplugDefinition(manifest=load_manifest(__file__), router=routes.router, on_start=_start, on_stop=_stop)

__all__ = ["CPLUG"]
