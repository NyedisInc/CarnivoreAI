
from __future__ import annotations

import asyncio
from typing import Callable, Optional

from src.core.deepsearch import fallback_hook
from src.plugins.save import capabilities, capture_hook, location_check, mcp, offload_mcp, offload_start, pipeline_row, routes, scheduler
from src.plugins.save.offload import batch_routes as offload_batch
from src.plugins.save.offload import push as offload_push
from src.plugins.save.offload import restore_batch_routes as offload_restore_batch
from src.plugins.save.service import RUNTIME
from src.plugins.save.vault import health, location
from src.plugins.save.fallback import BackupTranscripts
from src.plugins.save.port import RestorePoints
from src.plugins.sdk import CplugContext, CplugDefinition, load_manifest, ports, restore_points, save_triggers, transcript_files as tf, with_capabilities


FALLBACK_SOURCE_ID = "save"


class _Running:

    unsubscribe: Optional[Callable[[], None]] = None
    follower: Optional[scheduler.Follower] = None


async def _start(ctx: CplugContext) -> None:
    offload_push.bind(ctx.notify)
    ports.register(restore_points.PORT, RestorePoints())
    fallback_hook.register(FALLBACK_SOURCE_ID, BackupTranscripts())
    if _Running.unsubscribe is None:
        _Running.unsubscribe = save_triggers.subscribe(capture_hook.on_save)
    await asyncio.to_thread(offload_start.settle_on_start)
    pipeline_row.register()
    await asyncio.to_thread(pipeline_row.seed_from_disk, location.resolve_root(tf.state_dir()))
    _Running.follower = _Running.follower or scheduler.Follower()
    _Running.follower.start()
    offload_start.resend_in_background()


async def _stop(ctx: CplugContext) -> None:
    if _Running.unsubscribe is not None:
        _Running.unsubscribe()
        _Running.unsubscribe = None
    if _Running.follower is not None:
        await _Running.follower.stop()
        _Running.follower = None
    if offload_batch.RUNNER.stop_running():
        await asyncio.to_thread(offload_batch.RUNNER.join, scheduler.STOP_WAIT_SECONDS)
    if offload_restore_batch.RUNNER.stop_running():
        await asyncio.to_thread(offload_restore_batch.RUNNER.join, scheduler.STOP_WAIT_SECONDS)
    RUNTIME.reset()
    offload_push.unbind()
    await asyncio.to_thread(health.update, tf.state_dir(), active=False)
    ports.unregister(restore_points.PORT)
    pipeline_row.unregister()
    fallback_hook.unregister(FALLBACK_SOURCE_ID)


CPLUG = CplugDefinition(manifest=load_manifest(__file__), router=routes.router, tools=with_capabilities({**offload_mcp.TOOLS, **mcp.TOOLS}, capabilities.TABLE),
                        on_start=_start, on_stop=_stop,
                        settings_check=location_check.check_settings)

__all__ = ["CPLUG"]
