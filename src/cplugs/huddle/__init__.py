
import asyncio
import sqlite3
import time
from typing import Any

import structlog

from src.cplugs.huddle import artifact_browser, artifact_port, board_port, capabilities, client_writes, conversation_release, devtools_port, held, held_resume, mcp, routes, schedule, schedule_port, service, send_queue, task_sweep, told_log, legacy_approvals, push_delta, turn_return
from src.cplugs.huddle.nudge import scheduler as nudge_scheduler
from src.cplugs.huddle.roles import port as roles_port
from src.cplugs.huddle.cards import policy as card_policy, tx as card_tx
from src.cplugs.huddle.cards.port import TaskManagerCardPort
from src.cplugs.huddle.swarm_port import TaskManagerSwarmPort
from src.cplugs.sdk import CapabilityMissing, CplugDefinition, CplugSchemaError, load_manifest, with_capabilities
from src.cplugs.sdk import browser_pages
from src.cplugs.sdk.work import STORAGE
from src.cplugs.sdk.storage import PostBackupFailure
from src.cplugs.sdk.storage_backup import BackupFailed


logger = structlog.get_logger()


async def _dealing_step(ctx: Any) -> bool:
    try:
        keys = await asyncio.to_thread(lambda: [str(p["id"]) for p in ctx.projects.list(include_archived=True, strict=True)])
    except (CapabilityMissing, OSError, ValueError, KeyError) as exc:
        logger.warning("card_dealing_step_skipped", error_type=type(exc).__name__)
        return False
    store = service.store(ctx)

    def run() -> bool:
        with card_tx.write(store, set()) as conn:
            return card_policy.ensure_dealing_step(conn, keys, time.time())

    try:
        return await asyncio.to_thread(run)
    except (OSError, sqlite3.Error) as exc:
        logger.warning("card_dealing_step_failed", error_type=type(exc).__name__)
        return False


async def _start(ctx: Any) -> None:
    try:
        await asyncio.to_thread(ctx.work.open)
    except CplugSchemaError as exc:
        cause = ("walk_failed" if isinstance(exc, PostBackupFailure)
                 else "backup_failed" if isinstance(exc.__cause__, (BackupFailed, OSError, sqlite3.Error)) else "schema_refused")
        logger.error(f"cplug_start_{cause}", cplug="huddle", error=str(exc)[:300])
        raise
    except (OSError, sqlite3.Error) as exc:
        logger.warning("task_manager_storage_open_failed", error=str(exc))
    try:
        await asyncio.to_thread(task_sweep.sweep_all, ctx.storage)
    except (OSError, sqlite3.Error) as exc:
        logger.warning("task_manager_orphan_sweep_failed", error=str(exc))
    await _dealing_step(ctx)
    try:
        cleared = await asyncio.to_thread(service.store(ctx).sweep_read_claims)
        if cleared:
            logger.info("task_manager_read_claims_cleared", count=len(cleared), item_ids=cleared)
    except (OSError, sqlite3.Error) as exc:
        logger.warning("task_manager_read_claim_sweep_failed", error_type=type(exc).__name__, error=str(exc))
    try:
        cleared = await asyncio.to_thread(service.store(ctx).sweep_read_owners)
        if cleared:
            logger.info("task_manager_read_owners_cleared", count=len(cleared), item_ids=cleared)
    except (OSError, sqlite3.Error) as exc:
        logger.warning("task_manager_read_owner_sweep_failed", error_type=type(exc).__name__, error=str(exc))
    try:
        cleared = await asyncio.to_thread(service.store(ctx).sweep_stale_dots)
        if cleared:
            logger.info("task_manager_stale_dots_cleared", count=len(cleared), item_ids=cleared)
    except (OSError, sqlite3.Error) as exc:
        logger.warning("task_manager_stale_dot_sweep_failed", error_type=type(exc).__name__, error=str(exc))
    if ctx.has("swarm"):
        ctx.swarm.register_thread_port(TaskManagerSwarmPort(ctx))
        ctx.swarm.register_card_port(TaskManagerCardPort(ctx))
    schedule.start(ctx)
    conversation_release.start(ctx)
    turn_return.start(ctx)
    schedule_port.register(ctx)
    roles_port.register(ctx)
    nudge_scheduler.start(ctx)
    devtools_port.register(ctx)
    artifact_port.register(ctx)
    board_port.register(ctx)
    await send_queue.rearm_untold(ctx)
    await held_resume.resume(ctx)
    browser_pages.register(artifact_browser.KIND, artifact_browser.resolver(ctx))
    await legacy_approvals.retire(ctx)
    push_delta.start(ctx)


async def _stop(ctx: Any) -> None:
    push_delta.stop()
    conversation_release.stop()
    turn_return.stop()
    schedule_port.unregister()
    nudge_scheduler.stop()
    board_port.unregister()
    artifact_port.unregister()
    devtools_port.unregister()
    roles_port.unregister()
    held.reset()
    browser_pages.unregister(artifact_browser.KIND)
    send_queue.reset()
    told_log.reset()
    client_writes.reset()
    if ctx.has("swarm"):
        ctx.swarm.register_thread_port(None)
        ctx.swarm.register_card_port(None)
    schedule.stop()


async def _settings_saved(ctx: Any) -> None:
    nudge_scheduler.settings_saved()


CPLUG = CplugDefinition(manifest=load_manifest(__file__), router=routes.router, tools=with_capabilities(mcp.TOOLS, capabilities.TABLE), storage=STORAGE,
                        on_start=_start, on_stop=_stop, on_settings=_settings_saved)

__all__ = ["CPLUG"]
