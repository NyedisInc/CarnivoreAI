
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Optional, Union

import structlog

from src.api.session_sleep_routes import auto_sleep_by_uuid
from src.api.websocket import connection_manager
from src.config import settings
from src.core import resource_push
from src.core.attention_wiring import build_attention_watcher
from src.core.auto_sleep.idle_clock import IdleClock
from src.core.auto_sleep.mac_awake import MacAwakeGuard, reconcile_at_boot as reconcile_mac_awake_at_boot
from src.core.auto_sleep.sleeper import AutoSleeper
from src.core.automations import scheduler as automation_scheduler
from src.core.automations import seed as automation_seed
from src.core.automations import seed_backup as automation_seed_backup
from src.core.automations import wiring as automation_wiring
from src.core.boot.steps import BootStep, StepFn, teardown_slot
from src.core.boot.teardown import stop_task
from src.core.hosts.identity import is_remote_backend
from src.core.resource_push import topics as resource_topics

if TYPE_CHECKING:
    from src.core.boot.context import BootContext

logger = structlog.get_logger()

_LATE_WATCH_NAMES = ("git_status_watch", "session_tasks_watch", "machine_stats_watch", "server_log_watch", "stats_feed")


@dataclass
class _Held:

    tasks: dict[str, "asyncio.Task[object]"] = field(default_factory=dict)
    messaging_installed: Optional[object] = None
    notify_sources_task: Optional[object] = None


async def _start_mac_awake(ctx: "BootContext", _held: _Held) -> None:
    ctx.auto_sleep_clock = IdleClock()
    mac_awake_guard = MacAwakeGuard()
    ctx.app.state.mac_awake_guard = mac_awake_guard
    await asyncio.to_thread(reconcile_mac_awake_at_boot, mac_awake_guard, Path(settings.auth_config_file).expanduser())


async def _stop_mac_awake(ctx: "BootContext", _held: _Held) -> None:
    await asyncio.to_thread(ctx.app.state.mac_awake_guard.reconcile, 0)


async def _start_dispatcher(ctx: "BootContext", _held: _Held) -> None:
    from src.core.crosstalk.delivery.dispatcher import Dispatcher

    ctx.app.state.crosstalk_dispatcher = Dispatcher(ctx.app) if ctx.datastore_state.healthy else None
    if ctx.app.state.crosstalk_dispatcher is not None:
        await ctx.app.state.crosstalk_dispatcher.start()


def _stop_dispatcher(ctx: "BootContext", _held: _Held) -> None:
    if ctx.app.state.crosstalk_dispatcher is not None:
        ctx.app.state.crosstalk_dispatcher.close()


async def _start_messaging(ctx: "BootContext", held: _Held) -> None:
    from src.core.messaging import runtime as messaging_runtime

    ctx.app.state.messaging = None
    held.messaging_installed = await messaging_runtime.install(ctx.app) if ctx.datastore_state.healthy else None


async def _stop_messaging(_ctx: "BootContext", held: _Held) -> None:
    from src.core.messaging import runtime as messaging_runtime

    await messaging_runtime.uninstall(held.messaging_installed)


async def _start_watcher(ctx: "BootContext", held: _Held) -> None:
    from src.core.mcp.approvals import runtime as approval_runtime
    from src.core.session_token_usage import reader_state

    app = ctx.app
    await asyncio.to_thread(reader_state.install, settings.get_state_dir())
    await approval_runtime.install(app)
    attention_watcher = build_attention_watcher(
        ctx.session_manager,
        app_state=app.state,
        broadcast=connection_manager.broadcast_to_session,
        idle_clock=ctx.auto_sleep_clock,
    )
    app.state.attention_watcher = attention_watcher
    held.tasks["attention_watcher"] = asyncio.create_task(attention_watcher.run())


async def _stop_watcher(ctx: "BootContext", held: _Held) -> None:
    from src.core.session_token_usage import reader_state

    await ctx.stop_part("attention_watcher_task", lambda: stop_task(held.tasks.get("attention_watcher")))
    await ctx.stop_part("attention_reader_state", lambda: asyncio.to_thread(reader_state.stop))
    logger.info("attention_watcher_stopped")


def _start_notify_sources(ctx: "BootContext", held: _Held) -> None:
    from src.core.notifications.sources import lifecycle as notify_sources

    held.notify_sources_task = notify_sources.start(ctx.app.state, asyncio.get_running_loop())


async def _stop_notify_sources(_ctx: "BootContext", held: _Held) -> None:
    from src.core.notifications.sources import lifecycle as notify_sources

    await notify_sources.stop(held.notify_sources_task)


def _start_listing_push(ctx: "BootContext", held: _Held) -> None:
    from src.api.peer_listing_view import peer_view
    from src.api.session_listing_collections import listing_collections
    from src.core.federation.peer_listing_feed import PeerListingFeed
    from src.core.listing_push.publisher import ListingPublisher
    from src.core.resource_push.client_build import ClientBuildWatch
    from src.core.static_asset_keys import client_build_key
    from src.core.tmux_control import changes as tmux_changes

    app = ctx.app
    listing_publisher = ListingPublisher(
        listing_collections(app.state), app.state.event_hub.publish,
        lambda: app.state.event_hub.client_count,
        after_pass=ClientBuildWatch(client_build_key).check,
        feed=tmux_changes.control_feed(
            ctx.session_manager.tmux_socket_name,
            lambda: not any(is_remote_backend(b) for b in ctx.session_manager._registry.backends.values())),
    )
    app.state.event_hub.add_listener(listing_publisher.on_hub_publish)
    tmux_changes.add_listener(tmux_changes.wake_listener(listing_publisher.wake))
    app.state.listing_publisher = listing_publisher
    app.state.peer_listing_feed = PeerListingFeed(lambda: peer_view(app.state))
    app.state.event_hub.add_listener(app.state.peer_listing_feed.on_hub_publish)
    resource_push.add_topic_listener(resource_topics.AUTOMATIONS, listing_publisher.wake)
    held.tasks["listing_publisher"] = asyncio.create_task(listing_publisher.run())


async def _stop_listing_push(ctx: "BootContext", held: _Held) -> None:
    task = held.tasks.get("listing_publisher")
    await stop_task(task, wait=False)
    await ctx.stop_part("resource_push", resource_push.uninstall)
    await ctx.stop_part("listing_publisher_task", lambda: stop_task(task, cancel=False))


def _start_auto_sleep(ctx: "BootContext", held: _Held) -> None:
    app = ctx.app
    auto_sleeper = AutoSleeper(
        app.state, ctx.auto_sleep_clock,
        sleep=lambda session_uuid: auto_sleep_by_uuid(app.state, session_uuid),
    )
    app.state.auto_sleeper = auto_sleeper
    held.tasks["auto_sleep"] = asyncio.create_task(auto_sleeper.run())


async def _stop_auto_sleep(_ctx: "BootContext", held: _Held) -> None:
    await stop_task(held.tasks.get("auto_sleep"))


def _start_bridge_migration(ctx: "BootContext", held: _Held) -> None:
    from src.core.mcp_bridge.migration.migrator import BridgeMigrator

    state = ctx.app.state
    state.mcp_bridge_migrator = BridgeMigrator(state.session_manager)
    held.tasks["bridge_migration"] = asyncio.create_task(state.mcp_bridge_migrator.run(
        getattr(state.session_manager, "_boot_readopt_task", None)))


async def _stop_bridge_migration(ctx: "BootContext", held: _Held) -> None:
    await ctx.stop_part("bridge_migration_task", lambda: stop_task(held.tasks.get("bridge_migration")))
    logger.info("auto_sleep_stopped")


def _start_automations(ctx: "BootContext", _held: _Held) -> None:
    automation_scheduler.start(ctx.app.state, settings.get_state_dir())
    automation_wiring.register(settings.get_state_dir())
    automation_seed.apply(ctx.app.state.automation_store)
    automation_seed_backup.apply(ctx.app.state.automation_store)
    logger.info("attention_watcher_scheduled", tick_seconds=ctx.app.state.attention_watcher.tick_seconds)


async def _stop_automations(_ctx: "BootContext", _held: _Held) -> None:
    await automation_scheduler.stop()


def _start_work_backfill(_ctx: "BootContext", held: _Held) -> None:
    from src.core.db import db_path_for as _work_db_path
    from src.core.session_work_backfill import run_boot_backfill

    held.tasks["work_backfill"] = asyncio.create_task(asyncio.to_thread(
        run_boot_backfill, _work_db_path(settings.get_state_dir())))


async def _stop_work_backfill(_ctx: "BootContext", held: _Held) -> None:
    await stop_task(held.tasks["work_backfill"], cancel=False)


async def _stop_late_watches(ctx: "BootContext", _held: _Held) -> None:
    for name in _LATE_WATCH_NAMES:
        watch = getattr(ctx.app.state, name, None)
        if watch is not None:
            await ctx.stop_part(name, watch.stop)


def steps() -> list[BootStep]:
    held = _Held()

    def bind(fn: Callable[["BootContext", _Held], Union[None, Awaitable[None]]]) -> StepFn:
        return lambda ctx: fn(ctx, held)

    return [
        BootStep(name="mac_awake", order=420, stop_name="mac_awake_guard", start=bind(_start_mac_awake), stop=bind(_stop_mac_awake),
                 stop_order=teardown_slot(24)),
        BootStep(name="crosstalk_dispatcher", order=430, start=bind(_start_dispatcher), stop=bind(_stop_dispatcher),
                 stop_order=teardown_slot(27)),
        BootStep(name="messaging", order=440, stop_name="messaging_runtime", start=bind(_start_messaging), stop=bind(_stop_messaging),
                 stop_order=teardown_slot(28)),
        BootStep(name="attention_watcher", order=450, stop_parts=("attention_watcher_task", "attention_reader_state"), start=bind(_start_watcher), stop=bind(_stop_watcher),
                 stop_order=teardown_slot(29)),
        BootStep(name="notify_sources", order=480, start=bind(_start_notify_sources), stop=bind(_stop_notify_sources),
                 stop_order=teardown_slot(31)),
        BootStep(name="listing_push", order=490, stop_parts=("resource_push", "listing_publisher_task"), start=bind(_start_listing_push), stop=bind(_stop_listing_push),
                 stop_order=teardown_slot(26)),
        BootStep(name="auto_sleep", order=500, stop_name="auto_sleep_task", start=bind(_start_auto_sleep), stop=bind(_stop_auto_sleep),
                 stop_order=teardown_slot(20)),
        BootStep(name="mcp_bridge_migration", order=510, stop_parts=("bridge_migration_task",), start=bind(_start_bridge_migration),
                 stop=bind(_stop_bridge_migration), stop_order=teardown_slot(21)),
        BootStep(name="automations", order=520, stop_name="automation_scheduler", start=bind(_start_automations), stop=bind(_stop_automations),
                 stop_order=teardown_slot(22)),
        BootStep(name="work_backfill", order=540, stop_name="work_backfill_task", start=bind(_start_work_backfill), stop=bind(_stop_work_backfill),
                 stop_order=teardown_slot(38)),
        BootStep(name="late_watches", order=545, stop_parts=_LATE_WATCH_NAMES, stop=bind(_stop_late_watches), stop_order=teardown_slot(25)),
    ]
