
from __future__ import annotations

import asyncio
from typing import Any

import structlog

from src.cplugs.reviewboard.public import carry, links, wiring
from src.cplugs.reviewboard.public.availability import AVAILABILITY
from src.cplugs.reviewboard.public.deps import Unavailable
from src.cplugs.reviewboard.public.read import READER
from src.cplugs.reviewboard.public.service import SERVICE
from src.cplugs.reviewboard.public.settings import links_enabled
from src.cplugs.reviewboard.public.write import WRITER

logger = structlog.get_logger()
_running = False


async def _bring_up(ctx: Any) -> None:
    global _running
    new_dir = ctx.storage.path
    report = await asyncio.to_thread(carry.carry, new_dir.parent / carry.OLD_FOLDER, new_dir)
    if report.outcome == "refused":
        AVAILABILITY.set(report.reason)
        return
    AVAILABILITY.clear()
    READER.bind(wiring.build(ctx))
    write = wiring.build_write(ctx)
    WRITER.bind(write)
    _running = True
    try:
        await asyncio.to_thread(write.prune)
    except Unavailable as exc:
        logger.warning("reviewboard_public_prune_failed", reason=str(exc))
    await SERVICE.apply(ctx.settings_now())


async def _bring_down() -> None:
    global _running
    await SERVICE.stop()
    wiring.cancel_presence_timer()
    WRITER.unbind()
    READER.unbind()
    _running = False


async def start(ctx: Any) -> None:
    if links_enabled(ctx.settings_now()):
        await _bring_up(ctx)


async def stop(ctx: Any) -> None:
    await _bring_down()
    AVAILABILITY.clear()


async def settings_saved(ctx: Any) -> None:
    wanted = links_enabled(ctx.settings_now())
    if wanted and not _running:
        await _bring_up(ctx)
    elif wanted:
        await SERVICE.apply(ctx.settings_now())
    elif _running or SERVICE.listener is not None:
        await _bring_down()
        AVAILABILITY.clear()


async def before_purge(ctx: Any) -> None:
    if ctx.storage.db_path.exists():
        await asyncio.to_thread(links.revoke_all, ctx.storage)
