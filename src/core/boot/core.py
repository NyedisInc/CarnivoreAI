
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import structlog

from src.api.websocket import connection_manager
from src.config import settings
from src.core.boot.steps import BootStep, FailureMode, teardown_slot
from src.core.boot.teardown import stop_task
from src.core.cli_command import service as cli_shim
from src.core.companion_shell import index as companion_index
from src.core.composition import build_services
from src.core.event_hub import EventHub
from src.core.local_servers import LocalServersTracker
from src.core.log_monitor import LogMonitor
from src.core.server_log import breadcrumb as log_breadcrumb
from src.core.server_log import self_rotate as server_log_rotate
from src.core.sessions.background_store import SessionBackgroundStore
from src.core.ui_preferences_store import UiPreferencesStore

if TYPE_CHECKING:
    from src.core.boot.context import BootContext

logger = structlog.get_logger()


async def _start_core_services(ctx: "BootContext") -> None:
    ctx.ui_preferences_store = UiPreferencesStore(lambda: Path(settings.auth_config_file).expanduser())
    ctx.session_background_store = SessionBackgroundStore(path=settings.get_session_backgrounds_path)
    ctx.session_background_store.load()
    services = build_services(ui_preferences=ctx.ui_preferences_store)
    ctx.services = services
    ctx.app.state.services = services
    ctx.app.state.companion_index = await asyncio.to_thread(
        companion_index.install, services.session_manager._registry, settings.get_state_dir())
    await services.session_manager.lifespan_startup()


async def _close_remote_hosts(ctx: "BootContext") -> None:
    await ctx.session_manager.hosts.close_all()


async def _write_cli_shim(_ctx: "BootContext") -> None:
    await asyncio.to_thread(cli_shim.write_shim, settings.get_state_dir())


async def _publish_log_breadcrumb(_ctx: "BootContext") -> None:
    await asyncio.to_thread(log_breadcrumb.publish, settings.get_state_dir())


@dataclass
class _RotateHandle:

    task: Optional["asyncio.Task[None]"] = None


def _rotate_steps() -> list[BootStep]:
    held = _RotateHandle()

    def start(_ctx: "BootContext") -> None:
        held.task = server_log_rotate.start()

    async def stop(_ctx: "BootContext") -> None:
        await stop_task(held.task)

    return [BootStep(name="server_log_rotate", order=90, stop_name="log_rotate_task", start=start, stop=stop, stop_order=teardown_slot(34))]


def _build_log_monitor(ctx: "BootContext") -> None:
    ctx.log_monitor = LogMonitor(ctx.session_manager)


def _load_auth_config(ctx: "BootContext") -> None:
    ctx.auth_cfg = settings.load_auth_config()


async def _start_local_servers(ctx: "BootContext") -> None:
    ctx.local_servers = LocalServersTracker(loop=asyncio.get_running_loop())
    ctx.local_servers.attach(ctx.log_monitor, ctx.session_manager)
    await ctx.local_servers.start()


async def _stop_local_servers(ctx: "BootContext") -> None:
    if ctx.local_servers is not None:
        await ctx.local_servers.stop()


async def _start_log_monitoring(ctx: "BootContext") -> None:
    await ctx.log_monitor.start_monitoring()


async def _stop_log_monitoring(ctx: "BootContext") -> None:
    await ctx.log_monitor.stop_monitoring()


def _publish_components(ctx: "BootContext") -> None:
    state = ctx.app.state
    state.session_manager = ctx.session_manager
    state.log_monitor = ctx.log_monitor
    state.local_servers = ctx.local_servers
    state.refresh_store = ctx.refresh_store
    state.spectator_links = ctx.spectator_links_store


def _publish_preferences(ctx: "BootContext") -> None:
    ctx.app.state.notification_policy_store = ctx.notification_policy_store
    ctx.app.state.ui_preferences_store = ctx.ui_preferences_store


def _publish_event_hub(ctx: "BootContext") -> None:
    ctx.app.state.session_background_store = ctx.session_background_store
    ctx.app.state.connection_manager = connection_manager
    ctx.app.state.event_hub = EventHub()


def steps() -> list[BootStep]:
    return [
        BootStep(name="core_services", order=60, stop_name="remote_hosts", start=_start_core_services, stop=_close_remote_hosts,
                 stop_order=teardown_slot(32)),
        BootStep(name="cli_command_shim", order=70, start=_write_cli_shim, failure=FailureMode.DEGRADED,
                 degrades_on=(OSError,), failure_event="cli_command_shim_write_failed"),
        BootStep(name="server_log_breadcrumb", order=80, start=_publish_log_breadcrumb),
        *_rotate_steps(),
        BootStep(name="log_monitor", order=100, start=_build_log_monitor),
        BootStep(name="auth_config", order=110, start=_load_auth_config),
        BootStep(name="local_servers", order=160, start=_start_local_servers, stop=_stop_local_servers,
                 stop_order=teardown_slot(46)),
        BootStep(name="log_monitoring", order=170, stop_name="log_monitor", start=_start_log_monitoring, stop=_stop_log_monitoring,
                 stop_order=teardown_slot(45)),
        BootStep(name="app_state_components", order=210, start=_publish_components),
        BootStep(name="app_state_preferences", order=240, start=_publish_preferences),
        BootStep(name="event_hub", order=260, start=_publish_event_hub),
    ]
