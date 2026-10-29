
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import structlog

from src.api.request_log import flush_rollup
from src.config import settings
from src.core.boot.steps import BootStep, teardown_slot

if TYPE_CHECKING:
    from src.core.boot.context import BootContext

logger = structlog.get_logger()


@dataclass
class _HostHandle:

    host: Optional[object] = None


def _run_one_time_migrations(ctx: "BootContext", state_dir: Path) -> None:
    from src.cplugs.host.state import StateWriteFailed
    from src.cplugs.host.split_migration import migrate as migrate_split_plugins

    config_path = Path(settings.auth_config_file).expanduser()
    fresh_install = ctx.datastore_state.fresh_install
    try:
        migrate_split_plugins(state_dir, config_path, fresh_install)
    except (OSError, ValueError) as exc:
        logger.error("cplug_split_migration_failed", error=f"{type(exc).__name__}: {exc}")
    from src.cplugs.host.vault_location_migration import migrate as migrate_vault_location

    try:
        migrate_vault_location(state_dir, config_path)
    except StateWriteFailed as exc:
        logger.error("vault_location_migration_failed", error=f"{type(exc).__name__}: {exc}")
    from src.cplugs.host.swarm_default_migration import migrate as migrate_swarm_default

    try:
        migrate_swarm_default(state_dir, fresh_install)
    except StateWriteFailed as exc:
        logger.error("cplug_swarm_default_migration_failed", error=f"{type(exc).__name__}: {exc}")
    from src.cplugs.host.plugin_fold import migrate as migrate_folded_plugins

    try:
        migrate_folded_plugins(state_dir)
    except StateWriteFailed as exc:
        logger.error("cplug_fold_migration_failed", error=f"{type(exc).__name__}: {exc}")


def _host_steps() -> list[BootStep]:
    held = _HostHandle()

    async def start(ctx: "BootContext") -> None:
        app = ctx.app
        from src.cplugs.host import runtime as cplugs_host

        held.host = cplugs_host.install(app, settings.get_state_dir())
        from src.cplugs.host.legacy_disabled import import_disabled_plugins

        import_disabled_plugins(
            held.host.state_dir,
            app.state.ui_preferences_store.read()["values"].get("disabled_plugins") or [],
            {d.id: d.manifest for d in cplugs_host.definitions()},
        )
        from src.core.approvals import beast_grid_migration, beast_lifecycle

        beast_grid_migration.migrate(held.host.state_dir, Path(settings.auth_config_file).expanduser())
        beast_lifecycle.start(held.host.state_dir)
        from src.core.crosstalk import card_prefs_migration

        card_prefs_migration.migrate(held.host.state_dir, app.state.ui_preferences_store)
        _run_one_time_migrations(ctx, held.host.state_dir)
        await held.host.start()

    async def stop(ctx: "BootContext") -> None:
        from src.core.approvals import beast_lifecycle
        from src.cplugs.host import runtime as cplugs_host

        await ctx.stop_part("cplugs_host", lambda: cplugs_host.host_for(ctx.app).stop())
        await ctx.stop_part("beast_lifecycle", lambda: beast_lifecycle.stop(held.host.state_dir))

    async def start_sidecar(ctx: "BootContext") -> None:
        await _start_sidecar(ctx, held.host)

    return [
        BootStep(name="plugin_host", order=650, stop_parts=("cplugs_host", "beast_lifecycle"), start=start, stop=stop, stop_order=teardown_slot(3)),
        BootStep(name="sidecar_runtime", order=660, start=start_sidecar, stop=_stop_sidecar, stop_order=teardown_slot(2)),
    ]


async def _start_sidecar(ctx: "BootContext", host: object) -> None:
    from src.cplugs.host import sidecar_boot

    app = ctx.app
    app.state.sidecar_runtime = await sidecar_boot.boot(host, app, asyncio.get_running_loop())
    refresher = app.state.catalog_index_refresher
    refresher.after_pass = app.state.sidecar_runtime.index.sync
    refresher.hourly_while = app.state.sidecar_runtime.index.third_party_enabled


async def _stop_sidecar(ctx: "BootContext") -> None:
    await ctx.app.state.sidecar_runtime.stop()


def _start_card_push(ctx: "BootContext") -> None:
    from src.core.crosstalk import card_push as crosstalk_card_push

    crosstalk_card_push.install(
        ctx.app.state.event_hub.publish, asyncio.get_running_loop(), ctx.app.state.ui_preferences_store.read,
    )


def _stop_card_push(_ctx: "BootContext") -> None:
    from src.core.crosstalk import card_push as crosstalk_card_push

    crosstalk_card_push.uninstall()


def _tune_gc(_ctx: "BootContext") -> None:
    from src.core.perf_hooks import gc_tuning

    gc_tuning.tune_after_startup()


def _flush_request_log(_ctx: "BootContext") -> None:
    flush_rollup()


def steps() -> list[BootStep]:
    return [
        *_host_steps(),
        BootStep(name="crosstalk_card_push", order=670, start=_start_card_push, stop=_stop_card_push,
                 stop_order=teardown_slot(4)),
        BootStep(name="gc_tuning", order=680, start=_tune_gc),
        BootStep(name="request_log_rollup", order=690, stop=_flush_request_log, stop_order=teardown_slot(1)),
    ]
