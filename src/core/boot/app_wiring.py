
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from src.api import perf_routes, resource_bodies
from src.config import settings
from src.core import resource_push, shape_alert_wiring
from src.core.boot.steps import BootStep, teardown_slot
from src.core.catalog import account_push, guest_account, install_reporter
from src.core.companion_shell import reconcile as companion_reconcile

if TYPE_CHECKING:
    from src.core.boot.context import BootContext

logger = structlog.get_logger()


def _install_deepsearch_and_time_zone(ctx: "BootContext") -> None:
    from src.core.deepsearch import index_scope as deepsearch_index_scope, scope_migration as deepsearch_scope_migration
    from src.core.deepsearch.cache import db as deepsearch_cache_db
    from src.core.time_zone import app_time_zone

    store = ctx.ui_preferences_store
    deepsearch_index_scope.install(store.read)
    app_time_zone.install(store.read)
    deepsearch_scope_migration.migrate(Path(settings.get_state_dir()), store)
    deepsearch_cache_db.warm_in_background(Path(settings.get_state_dir()))


def _uninstall_deepsearch(_ctx: "BootContext") -> None:
    from src.core.deepsearch import index_scope as deepsearch_index_scope

    deepsearch_index_scope.uninstall()


def _install_pushes(ctx: "BootContext") -> None:
    state = ctx.app.state
    account_push.install(state)
    if guest_account.background_enabled():
        guest_account.install_fold(state)
        install_reporter.schedule_backfill(ctx.services, Path(settings.auth_config_file).expanduser())
    resource_push.install(state.event_hub.publish, with_bodies=True, wants_bodies=state.event_hub.has_owner_client)
    resource_bodies.register(state)
    state.event_hub.add_listener(resource_push.on_hub_publish)


def _close_orphan_pack_ops(_ctx: "BootContext") -> None:
    from src.core.pack.move import op_status as pack_op_status

    pack_op_status.close_orphans_at_boot(settings.get_state_dir())


def _install_companion_reconcile(ctx: "BootContext") -> None:
    app = ctx.app
    app.state.companion_reconciler = companion_reconcile.install(app, asyncio.get_running_loop())
    app.state.event_hub.add_listener(companion_reconcile.on_hub_publish)
    companion_reconcile.request_when_done(getattr(ctx.session_manager, "_boot_readopt_task", None))


def _install_dev_hooks(ctx: "BootContext") -> None:
    perf_routes.start_if_configured(ctx.app.state)
    shape_alert_wiring.install(ctx.app.state, asyncio.get_running_loop(), enabled=settings.dev_shape_alerts)


def _install_app_alerts(ctx: "BootContext") -> None:
    from src.core.app_alerts import wiring as app_alerts_wiring
    from src.core.db import db_path_for as _alerts_db_path

    app_alerts_wiring.install(ctx.app.state, asyncio.get_running_loop(), _alerts_db_path(settings.get_state_dir()))


def _uninstall_app_alerts(_ctx: "BootContext") -> None:
    from src.core.app_alerts import wiring as app_alerts_unwire

    app_alerts_unwire.uninstall()


def _install_account_notice(ctx: "BootContext") -> None:
    from src.core.account_notice import runner as account_notice_runner

    app = ctx.app
    account_notice_runner.install(
        settings.get_state_dir(), pairing=lambda: getattr(getattr(app.state, "phone_link", None), "pairing", None))


def _uninstall_account_notice(_ctx: "BootContext") -> None:
    from src.core.account_notice import runner as account_notice_unwire

    account_notice_unwire.uninstall()


def _install_self_check(ctx: "BootContext") -> None:
    from src.core.self_check import monitor as self_check_monitor

    self_check_monitor.install(manager=ctx.session_manager)


def _uninstall_self_check(_ctx: "BootContext") -> None:
    from src.core.self_check import monitor as self_check_unwire

    self_check_unwire.uninstall()


def _install_transcript_manifest(_ctx: "BootContext") -> None:
    from src.core.transcript_manifest import condition as transcript_manifest_condition

    transcript_manifest_condition.install(settings.get_state_dir())


def _uninstall_transcript_manifest(_ctx: "BootContext") -> None:
    from src.core.transcript_manifest import condition as transcript_manifest_unwire

    transcript_manifest_unwire.uninstall()


def _install_pipeline(_ctx: "BootContext") -> None:
    from src.core.pipeline import wiring as pipeline_wiring

    pipeline_wiring.install()


def _uninstall_pipeline(_ctx: "BootContext") -> None:
    from src.core.pipeline import wiring as pipeline_unwire

    pipeline_unwire.uninstall()


def steps() -> list[BootStep]:
    return [
        BootStep(name="deepsearch_scope", order=250, stop_name="deepsearch_index_scope", start=_install_deepsearch_and_time_zone, stop=_uninstall_deepsearch,
                 stop_order=teardown_slot(14)),
        BootStep(name="pushes", order=270, start=_install_pushes),
        BootStep(name="pack_orphan_ops", order=280, start=_close_orphan_pack_ops),
        BootStep(name="companion_reconcile", order=290, start=_install_companion_reconcile),
        BootStep(name="dev_hooks", order=300, start=_install_dev_hooks),
        BootStep(name="app_alerts", order=310, start=_install_app_alerts, stop=_uninstall_app_alerts,
                 stop_order=teardown_slot(12)),
        BootStep(name="account_notice", order=320, start=_install_account_notice, stop=_uninstall_account_notice,
                 stop_order=teardown_slot(9)),
        BootStep(name="self_check", order=330, start=_install_self_check, stop=_uninstall_self_check,
                 stop_order=teardown_slot(10)),
        BootStep(name="transcript_manifest", order=340, start=_install_transcript_manifest,
                 stop=_uninstall_transcript_manifest, stop_order=teardown_slot(11)),
        BootStep(name="pipeline", order=350, start=_install_pipeline, stop=_uninstall_pipeline,
                 stop_order=teardown_slot(13)),
    ]
