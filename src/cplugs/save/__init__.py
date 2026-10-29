
from __future__ import annotations

import asyncio
from typing import Callable, Optional

from src.core.deepsearch import fallback_hook
from src.cplugs.save import capabilities, capture_hook, location_check, mcp, pipeline_row, routes, scheduler
from src.cplugs.save.service import RUNTIME
from src.cplugs.save.vault import health, location
from src.cplugs.save.fallback import BackupTranscripts
from src.cplugs.save.port import RestorePoints
from src.cplugs.sdk import CplugContext, CplugDefinition, load_manifest, ports, restore_points, save_triggers, transcript_files as tf, with_capabilities


FALLBACK_SOURCE_ID = "save"


class _Running:

    unsubscribe: Optional[Callable[[], None]] = None
    follower: Optional[scheduler.Follower] = None


async def _start(ctx: CplugContext) -> None:
    ports.register(restore_points.PORT, RestorePoints())
    fallback_hook.register(FALLBACK_SOURCE_ID, BackupTranscripts())
    if _Running.unsubscribe is None:
        _Running.unsubscribe = save_triggers.subscribe(capture_hook.on_save)
    _Running.follower = _Running.follower or scheduler.Follower()
    _Running.follower.start()
    pipeline_row.register()
    await asyncio.to_thread(pipeline_row.seed_from_disk, location.resolve_root(tf.state_dir()))


async def _stop(ctx: CplugContext) -> None:
    if _Running.unsubscribe is not None:
        _Running.unsubscribe()
        _Running.unsubscribe = None
    if _Running.follower is not None:
        await _Running.follower.stop()
        _Running.follower = None
    RUNTIME.reset()
    await asyncio.to_thread(health.update, tf.state_dir(), active=False)
    ports.unregister(restore_points.PORT)
    pipeline_row.unregister()
    fallback_hook.unregister(FALLBACK_SOURCE_ID)


CPLUG = CplugDefinition(manifest=load_manifest(__file__), router=routes.router, tools=with_capabilities(mcp.TOOLS, capabilities.TABLE),
                        on_start=_start, on_stop=_stop,
                        settings_check=location_check.check_settings)

__all__ = ["CPLUG"]
