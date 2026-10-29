
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

import structlog

from src.config import settings
from src.core import relay_lifecycle
from src.core.boot.steps import BootStep, teardown_slot
from src.core.boot.teardown import stop_task
from src.core.phone_link import boot as phone_link_boot
from src.core.refresh_store import RefreshStore
from src.core.relay_identity.account import RelayAccount
from src.core.spectator_links_store import SpectatorLinksStore
from src.core.version import startup_version

if TYPE_CHECKING:
    from src.core.boot.context import BootContext

logger = structlog.get_logger()

REFRESH_PURGE_INTERVAL_SECONDS = 6 * 60 * 60
_PURGE_ERROR_BACKOFF_SECONDS = 60


async def _rollup_mcp_usage() -> None:
    from src.core.db import DatastoreError
    from src.core.mcp_usage import rollup

    try:
        await asyncio.to_thread(rollup.run)
    except (sqlite3.Error, OSError, ValueError, RuntimeError, DatastoreError) as exc:
        logger.warning("mcp_usage_rollup_failed", error_type=type(exc).__name__, error=str(exc))


async def _prune_mcp_events() -> None:
    from src.core.db import DatastoreError
    from src.core.flow_data import mcp_events

    try:
        removed = await asyncio.to_thread(mcp_events.prune)
    except (sqlite3.Error, OSError, DatastoreError) as exc:
        logger.warning("mcp_events_prune_failed", error_type=type(exc).__name__, error=str(exc))
        return
    if removed:
        logger.info("mcp_events_pruned", removed=removed)


async def refresh_purge_loop(store: RefreshStore, *, spectator_store: Optional[SpectatorLinksStore] = None) -> None:
    await _rollup_mcp_usage()
    while True:
        try:
            await asyncio.sleep(REFRESH_PURGE_INTERVAL_SECONDS)
            await store.purge_expired()
            if spectator_store is not None:
                await spectator_store.purge_expired()
            await _rollup_mcp_usage()
            await _prune_mcp_events()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.error("refresh_purge_loop_error", error=str(e))
            await asyncio.sleep(_PURGE_ERROR_BACKOFF_SECONDS)


async def _start_refresh_store(ctx: "BootContext") -> None:
    ctx.refresh_store = RefreshStore(str(settings.get_refresh_tokens_path()))
    await ctx.refresh_store.init()


async def _close_refresh_store(ctx: "BootContext") -> None:
    if ctx.refresh_store is not None:
        await ctx.refresh_store.close()


async def _start_spectator_store(ctx: "BootContext") -> None:
    from src.core.db import db_path_for as _cloude_db_path

    ctx.spectator_links_store = SpectatorLinksStore(str(_cloude_db_path(settings.get_state_dir())))
    await ctx.spectator_links_store.init()


async def _close_spectator_store(ctx: "BootContext") -> None:
    if ctx.spectator_links_store is not None:
        await ctx.spectator_links_store.close()


@dataclass
class _PurgeHandle:

    task: Optional["asyncio.Task[None]"] = None


def _purge_steps() -> list[BootStep]:
    held = _PurgeHandle()

    def start(ctx: "BootContext") -> None:
        held.task = asyncio.create_task(refresh_purge_loop(ctx.refresh_store, spectator_store=ctx.spectator_links_store))

    async def stop(_ctx: "BootContext") -> None:
        await stop_task(held.task)

    return [BootStep(name="refresh_purge_loop", order=200, stop_name="refresh_purge_task", start=start, stop=stop, stop_order=teardown_slot(39))]


async def _start_relay(ctx: "BootContext") -> None:
    from src.core.db import db_path_for as _cloude_db_path

    app = ctx.app
    relay_account = RelayAccount(settings.get_state_dir(), ctx.services.catalog.api_base_url)
    app.state.relay = relay_lifecycle.build(
        ctx.auth_cfg.relay, registry=ctx.services.registry, store=ctx.spectator_links_store,
        db_path=_cloude_db_path(settings.get_state_dir()),
        version=startup_version(), account=relay_account,
    )
    if app.state.relay is not None:
        await app.state.relay.start_if_live()
    phone_link_boot.start(app, ctx.auth_cfg.relay, settings.get_state_dir(), _cloude_db_path(settings.get_state_dir()),
                          startup_version(), relay_account)


async def _stop_relay(ctx: "BootContext") -> None:
    if getattr(ctx.app.state, "relay", None) is not None:
        await ctx.app.state.relay.aclose()


async def _stop_phone_link(ctx: "BootContext") -> None:
    await phone_link_boot.stop(ctx.app)


def steps() -> list[BootStep]:
    return [
        BootStep(name="refresh_store", order=180, start=_start_refresh_store, stop=_close_refresh_store,
                 stop_order=teardown_slot(40)),
        BootStep(name="spectator_links_store", order=190, start=_start_spectator_store, stop=_close_spectator_store,
                 stop_order=teardown_slot(43), stop_requires=("spectator_relay",)),
        *_purge_steps(),
        BootStep(name="relay", order=220, stop_name="spectator_relay", start=_start_relay, stop=_stop_relay, stop_order=teardown_slot(42)),
        BootStep(name="phone_link", order=230, stop_name="phone_link_boot", stop=_stop_phone_link, stop_order=teardown_slot(41)),
    ]
