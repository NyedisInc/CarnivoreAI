
import os
import json
import logging
import sqlite3
import structlog
import asyncio
from contextlib import asynccontextmanager, closing, suppress
from pathlib import Path
from urllib.parse import parse_qs
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from src.config import settings, StateDirUnavailableError
from src.core.server_log import breadcrumb as log_breadcrumb
from src.core.server_log import self_rotate as server_log_rotate
from src.core.server_log import redact as log_redaction
from src.security_headers import stamp_security_headers
from src.api.account_gates import AccountRequired, account_required_handler
from src.api.peer_route_guard import PeerForwarded, peer_route_guard
from src.api.request_log import RequestLogMiddleware
from src.api.host_guard import HostGuardMiddleware
from src.api.joined_lockdown import JoinedLockdownMiddleware
from src.api.json_gzip import JsonGzipMiddleware
from src.core.composition import build_services
from src.core import theme_paths
from src.core.log_level import expiry as live_log_level_expiry, live as live_log_level
from src.core.companion_shell import index as companion_index, reconcile as companion_reconcile
from src.core.session_manager import SessionManager
from src.core.log_monitor import LogMonitor
from src.core.local_servers import LocalServersTracker
from src.core.refresh_store import RefreshStore
from src.core.spectator_links_store import SpectatorLinksStore
from src.core import relay_lifecycle
from src.core.relay_identity.account import RelayAccount
from src.api.catalog_required_routes import run_required_pass
from src.cplugs.host.adoption import run_adoption_pass
from src.cplugs.host.catalog_move import run_catalog_move_pass
from src.core.skills.auto_update import after_refresh_hook, run_auto_update_pass
from src.core.skills.journal_recovery import recover_pending
from src.core.skills.project_scope import ProjectPathRefused, known_project_roots
from src.core.pipe_prune import PipePruner
from src.core.skills.sweeper import SkillSweeper
from src.core.upload_sweeper import UploadSweeper, datastore_project_paths
from src.core.catalog import account_push, client as catalog_client, guest_account, install_reporter
from src.core import resource_push
from src.core.resource_push import topics as resource_topics
from src.core.catalog import theme_migration
from src.core.catalog.index_refresher import IndexRefresher
from src.core.notifications import install as notifications_install
from src.core.session_notification_policy import (
    NotificationPolicyStore,
    hydrate_from_datastore as hydrate_notification_policy,
)
from src.core import claude_hooks
from src.core.attention_wiring import build_attention_watcher
from src.core.auto_sleep.idle_clock import IdleClock
from src.core.auto_sleep.mac_awake import MacAwakeGuard, reconcile_at_boot as reconcile_mac_awake_at_boot
from src.core.auto_sleep.sleeper import AutoSleeper
from src.core.automations import scheduler as automation_scheduler
from src.core.automations import seed as automation_seed
from src.core.automations import seed_backup as automation_seed_backup
from src.core.automations import wiring as automation_wiring
from src.api.session_sleep_routes import auto_sleep_by_uuid
from src.core.provider_ledger import poller as provider_ledger_poller
from src.core.db_integrity_task import DatabaseIntegrityScheduler
from src.core.session_journal_task import SessionJournalScheduler
from src.core.version import resolve_version, startup_version
from src.core.cli_command import service as cli_shim
from src.core.static_serving import (
    maybe_gzip_file_response,
    warm_static_gzip_cache,
    keyed_page_response,
    render_compressible_html_response,
)
from src.core import static_asset_keys
from src.core.mcp.channel import GRACEFUL_SHUTDOWN_S
from src.core.update_check import UpdateChecker
from src.core.setup_state import (
    current_bind_report,
    current_exposure,
    current_setup_state,
    record_bound_host,
)
from src.api.setup_routes import router as setup_router, page_router as setup_page_router
from src.api.mcp_routes import router as mcp_router
from src.api import version_routes
from src.api import perf_routes
from src.api.version_routes import router as version_router, set_update_checker
from src.api.routes import router as api_router
from src.api.websocket import router as ws_router
from src.api.events_routes import router as events_ws_router
from src.api.browser_socket import router as browser_ws_router
from src.core.browsers.manager import BrowserManager
from src.api.auth import limiter as auth_limiter, require_auth
from src.api.auth_routes import router as auth_router
from src.api.config_files_routes import router as config_files_router
from src.api.session_groups_routes import router as session_groups_router
from src.api.session_group_icon_routes import router as session_group_icon_router
from src.api.restart_routes import router as restart_router
from src.api.restore_offer_routes import router as restore_offer_router
from src.api.status_routes import router as status_router
from src.core.computers import membership
from src.core.phone_link import boot as phone_link_boot
from src.api.attention_routes import router as attention_router
from src.api.preferences_routes import router as preferences_router
from src.api.widget_bars_routes import router as widget_bars_router
from src.api.websocket import connection_manager
from src.core.sessions.background_store import SessionBackgroundStore
from src.core.ui_preferences_store import UiPreferencesStore
from src.core.event_hub import EventHub
from src.core import shape_alert_wiring
from src.api.toast_routes import router as toast_router
try:
    settings.get_state_dir()
except StateDirUnavailableError as exc:
    import sys as _sys

    _banner = f"""
========================================
CLOUDE CODE - STATE DIRECTORY ERROR
========================================

{exc}

The server refuses to start rather than write your session data,
pinned themes, unread flags, or refresh tokens somewhere you did not
choose (or silently drop them in a temp directory that macOS purges on
reboot).

To fix:
1. Make the target directory writable, or
2. Set CLOUDE_STATE_DIR in .env to a writable path, then restart.
========================================
"""
    print(_banner, file=_sys.stderr)
    _error_log = Path("/tmp/cloude-code-startup-error.log")
    try:
        with open(_error_log, "w") as _f:
            _f.write(_banner)
        print(f"\nError details written to: {_error_log}", file=_sys.stderr)
    except OSError:
        pass
    _sys.exit(1)

live_log_level.apply_level(live_log_level_expiry.boot_level(
    settings.log_level, Path(settings.auth_config_file).expanduser()
))
structlog.configure(
    processors=[*log_redaction.shared_processors(), structlog.processors.JSONRenderer()],
    wrapper_class=live_log_level.LiveLevelBoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()


session_manager: SessionManager = None
log_monitor: LogMonitor = None
local_servers: LocalServersTracker = None
refresh_store: RefreshStore = None
_refresh_purge_task: asyncio.Task = None
spectator_links_store: SpectatorLinksStore = None


_REFRESH_PURGE_INTERVAL_SECONDS = 6 * 60 * 60


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


async def _refresh_purge_loop(store: RefreshStore, *, spectator_store=None):
    await _rollup_mcp_usage()
    while True:
        try:
            await asyncio.sleep(_REFRESH_PURGE_INTERVAL_SECONDS)
            await store.purge_expired()
            if spectator_store is not None:
                await spectator_store.purge_expired()
            await _rollup_mcp_usage()
            await _prune_mcp_events()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("refresh_purge_loop_error", error=str(e))
            await asyncio.sleep(60)



def _read_config_version(config_path: Path) -> object:
    from src.core.db_state import CANNOT_DETERMINE
    try:
        with open(config_path) as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return CANNOT_DETERMINE
    value = raw.get("config_version") if isinstance(raw, dict) else None
    return value if isinstance(value, int) else CANNOT_DETERMINE


@asynccontextmanager
async def lifespan(app: FastAPI):
    global session_manager, log_monitor, local_servers
    global refresh_store, _refresh_purge_task
    global spectator_links_store

    logger.info("application_starting", version=resolve_version() or "unknown")
    live_log_level_expiry.arm_at_boot(settings.log_level, Path(settings.auth_config_file).expanduser())

    from src.core.mcp_usage import old_names as _old_name_counter

    _old_name_counter.install()

    from src.core.mcp_usage import old_names as _old_name_counter

    _old_name_counter.install()

    from src.core.config_migration import ensure_config_migrated
    from src.core.config_writer import tighten_existing as _tighten_config_modes

    _tighten_config_modes(Path(settings.auth_config_file).expanduser())
    ensure_config_migrated(Path(settings.auth_config_file).expanduser())
    from src.core.swarm.legacy_pack_migration import migrate as migrate_legacy_pack

    migrate_legacy_pack(Path(settings.auth_config_file).expanduser(), settings.get_state_dir())
    from src.core.browser_pages import open_pages as _open_pages

    _open_pages.configure(settings.get_state_dir())
    from src.core.open_files import open_list as _open_files

    _open_files.configure(settings.get_state_dir())
    from src.core import row_looks as _row_looks

    _row_looks.configure(settings.get_state_dir())
    settings.ensure_wrapper_defaults()

    from src.core.db_migration import ensure_db_migrated
    datastore_state = ensure_db_migrated(
        settings.get_state_dir(),
        _read_config_version(Path(settings.auth_config_file).expanduser()),
        resolve_version() or None,
    )
    app.state.datastore_state = datastore_state
    version_routes.set_datastore_state(datastore_state)
    if not datastore_state.healthy:
        logger.warning(
            "datastore_degraded",
            status=datastore_state.status,
            schema_version=datastore_state.schema_version,
            message=datastore_state.message,
        )

    from src.core.work import boot as work_boot
    await asyncio.to_thread(work_boot.prepare, settings.get_state_dir(), datastore_state.healthy)

    if datastore_state.healthy:
        from src.api import project_pack_routes
        await asyncio.to_thread(project_pack_routes.recover_interrupted_jobs)

    ui_preferences_store = UiPreferencesStore(
        lambda: Path(settings.auth_config_file).expanduser()
    )
    session_background_store = SessionBackgroundStore(
        path=settings.get_session_backgrounds_path
    )
    session_background_store.load()
    services = build_services(ui_preferences=ui_preferences_store)
    session_manager = services.session_manager
    app.state.services = services
    app.state.companion_index = await asyncio.to_thread(
        companion_index.install, session_manager._registry, settings.get_state_dir())
    await session_manager.lifespan_startup()
    try:
        await asyncio.to_thread(cli_shim.write_shim, settings.get_state_dir())
    except OSError as exc:
        logger.warning("cli_command_shim_write_failed", error=str(exc))
    await asyncio.to_thread(log_breadcrumb.publish, settings.get_state_dir())
    log_rotate_task = server_log_rotate.start()
    log_monitor = LogMonitor(session_manager)

    auth_cfg = settings.load_auth_config()

    app.state.session_import_notice = None
    # could not
    app.state.project_reconcile_notice = None
    if datastore_state.healthy:
        from src.core.projects_config_migration import (
            migrate_projects_out_of_config,
        )

        _projects_migration = migrate_projects_out_of_config(
            settings.get_state_dir(),
            Path(settings.auth_config_file).expanduser(),
        )
        app.state.project_reconcile_notice = _projects_migration.notice()
        if not _projects_migration.ok:
            logger.warning(
                "projects_config_migration_incomplete",
                reason=_projects_migration.reason,
                detail=_projects_migration.detail,
            )
        else:
            logger.info(
                "projects_config_migration",
                reason=_projects_migration.reason,
                imported=len(_projects_migration.imported),
                imported_undetermined=len(
                    _projects_migration.imported_undetermined
                ),
            )
        settings._auth_config_cache = None
        auth_cfg = settings.load_auth_config()

        from src.core.db import connect, db_path_for, transaction
        from src.core.session_attribution import backfill_attribution
        from src.core.session_import import run_first_run_import
        from src.core.session_project_binding import correct_shallow_derivations
        from src.core.session_stage_a_boundary import record_boundary
        from src.core.tmux_listing import coerce_listing
        from src.core.tmux_session_cwd import make_working_dir_probe

        try:
            _listing = coerce_listing(session_manager.list_attachable_sessions())
            with closing(
                connect(db_path_for(settings.get_state_dir()))
            ) as _import_conn:
                with transaction(_import_conn):
                    record_boundary(_import_conn)
                    _import_result = run_first_run_import(
                        _import_conn,
                        listing=_listing,
                        owned_tmux_names=set(services.owned_tmux.names),
                        socket=session_manager.tmux_socket_name(),
                        working_dir_probe=make_working_dir_probe(
                            session_manager.tmux_socket_name()
                        ),
                        log_dir=settings.get_log_dir(),
                    )
                app.state.session_import_notice = (
                    _import_result.home_screen_notice()
                )
                logger.info(
                    "first_run_import",
                    outcome=_import_result.outcome,
                    sessions_imported=_import_result.sessions_imported,
                    listing_ok=_listing.ok,
                    listing_reason=_listing.reason,
                )
                with closing(
                    connect(db_path_for(settings.get_state_dir()))
                ) as _attr_conn:
                    with transaction(_attr_conn):
                        _rehomed = correct_shallow_derivations(_attr_conn)
                        _attr_result = backfill_attribution(
                            _attr_conn,
                            working_dir_probe=make_working_dir_probe(
                                session_manager.tmux_socket_name()
                            ),
                        )
                logger.info(
                    "session_attribution_backfill_boot",
                    considered=_attr_result.considered,
                    attributed_project=_attr_result.attributed_project,
                    attributed_none=_attr_result.attributed_none,
                    still_unknown=_attr_result.still_unknown,
                    rehomed_to_deeper_project=_rehomed,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("first_run_import_failed", error=str(exc))

    from src.core.db import db_path_for as _db_path_for

    notification_policy_store = NotificationPolicyStore()
    hydrate_notification_policy(
        notification_policy_store, _db_path_for(settings.get_state_dir())
    )

    session_manager.attach_notification_policy_store(notification_policy_store)
    notifications_installed = await notifications_install.install(app.state, session_manager)

    try:
        claude_hooks.strip_managed_hooks(claude_hooks.default_settings_path())
    except Exception as exc:
        logger.warning("claude_hooks_strip_failed", error=str(exc))

    # Plan v3.2
    local_servers = LocalServersTracker(loop=asyncio.get_running_loop())
    local_servers.attach(log_monitor, session_manager)
    await local_servers.start()

    await log_monitor.start_monitoring()

    # CLOUDE_STATE_DIR
    db_path = str(settings.get_refresh_tokens_path())
    refresh_store = RefreshStore(db_path)
    await refresh_store.init()

    from src.core.db import db_path_for as _cloude_db_path
    spectator_links_store = SpectatorLinksStore(
        str(_cloude_db_path(settings.get_state_dir()))
    )
    await spectator_links_store.init()

    _refresh_purge_task = asyncio.create_task(
        _refresh_purge_loop(refresh_store, spectator_store=spectator_links_store)
    )

    app.state.session_manager = session_manager
    app.state.log_monitor = log_monitor
    app.state.local_servers = local_servers
    app.state.refresh_store = refresh_store
    app.state.spectator_links = spectator_links_store
    relay_account = RelayAccount(settings.get_state_dir(), services.catalog.api_base_url)
    app.state.relay = relay_lifecycle.build(
        auth_cfg.relay, registry=services.registry, store=spectator_links_store,
        db_path=_cloude_db_path(settings.get_state_dir()),
        version=startup_version(), account=relay_account,
    )
    if app.state.relay is not None:
        await app.state.relay.start_if_live()
    phone_link_boot.start(app, auth_cfg.relay, settings.get_state_dir(), _cloude_db_path(settings.get_state_dir()), startup_version(), relay_account)
    app.state.notification_policy_store = notification_policy_store
    app.state.ui_preferences_store = ui_preferences_store
    from src.core.deepsearch import index_scope as deepsearch_index_scope, scope_migration as deepsearch_scope_migration

    deepsearch_index_scope.install(ui_preferences_store.read)
    from src.core.time_zone import app_time_zone

    app_time_zone.install(ui_preferences_store.read)
    deepsearch_scope_migration.migrate(Path(settings.get_state_dir()), ui_preferences_store)
    from src.core.deepsearch.cache import db as deepsearch_cache_db

    deepsearch_cache_db.warm_in_background(Path(settings.get_state_dir()))
    app.state.session_background_store = session_background_store
    app.state.connection_manager = connection_manager
    app.state.event_hub = EventHub()
    account_push.install(app.state)
    if guest_account.background_enabled():
        guest_account.install_fold(app.state)
        install_reporter.schedule_backfill(services, Path(settings.auth_config_file).expanduser())
    resource_push.install(app.state.event_hub.publish)
    app.state.event_hub.add_listener(resource_push.on_hub_publish)
    from src.core.pack.move import op_status as pack_op_status

    pack_op_status.close_orphans_at_boot(settings.get_state_dir())
    app.state.companion_reconciler = companion_reconcile.install(app, asyncio.get_running_loop())
    app.state.event_hub.add_listener(companion_reconcile.on_hub_publish)
    companion_reconcile.request_when_done(getattr(session_manager, "_boot_readopt_task", None))
    perf_routes.start_if_configured(app.state)
    shape_alert_wiring.install(
        app.state, asyncio.get_running_loop(), enabled=settings.dev_shape_alerts
    )
    from src.core.app_alerts import wiring as app_alerts_wiring
    from src.core.db import db_path_for as _alerts_db_path

    app_alerts_wiring.install(app.state, asyncio.get_running_loop(), _alerts_db_path(settings.get_state_dir()))
    from src.core.account_notice import runner as account_notice_runner

    account_notice_runner.install(
        settings.get_state_dir(), pairing=lambda: getattr(getattr(app.state, "phone_link", None), "pairing", None))
    from src.core.self_check import monitor as self_check_monitor

    self_check_monitor.install(manager=session_manager)
    from src.core.transcript_manifest import condition as transcript_manifest_condition

    transcript_manifest_condition.install(settings.get_state_dir())
    from src.core.pipeline import wiring as pipeline_wiring

    pipeline_wiring.install()

    browser_manager = BrowserManager(
        settings.get_state_dir(), lambda: settings.load_auth_config().browser
    )
    app.state.browser_manager = browser_manager
    browser_sweep_task = asyncio.create_task(browser_manager.boot_sweep())

    upload_sweeper_task = None
    if auth_cfg.uploads.enabled:
        from src.core.project_authority import resolve_projects

        cfg = auth_cfg.uploads
        upload_sweeper = UploadSweeper(
            ttl_seconds=cfg.ttl_seconds,
            interval_seconds=cfg.sweep_interval_seconds,
            # could not
            # nothing at all
            # could not
            project_paths=datastore_project_paths(
                resolve_projects(settings.get_state_dir())
            ),
            default_dir=settings.get_working_dir(),
        )
        app.state.upload_sweeper = upload_sweeper
        upload_sweeper_task = asyncio.create_task(upload_sweeper.run())
        logger.info(
            "upload_sweeper_scheduled",
            interval_seconds=cfg.sweep_interval_seconds,
            ttl_seconds=cfg.ttl_seconds,
        )

    def _known_projects() -> frozenset:
        try:
            return known_project_roots(settings.get_state_dir())
        except ProjectPathRefused:
            return frozenset()

    skill_sweeper = SkillSweeper(
        install_roots=services.install_roots, project_roots=_known_projects
    )
    app.state.skill_sweeper = skill_sweeper
    skill_sweeper_task = asyncio.create_task(skill_sweeper.run())

    pipe_pruner_task = asyncio.create_task(
        PipePruner(
            log_dir=settings.get_log_dir(),
            state_dir=settings.get_state_dir(),
            socket_name=session_manager.tmux_socket_name(),
        ).run()
    )

    async def _recover_skill_updates() -> dict:
        roots = services.install_roots
        try:
            counts = await asyncio.to_thread(
                recover_pending, roots.pending_dir(), roots
            )
        except (OSError, ValueError) as exc:
            logger.warning("skill_journal_recovery_failed", error=str(exc))
            return {}
        if any(counts.values()):
            logger.info("skill_journal_recovery", **counts)
            resource_push.notify(resource_topics.THEMES)
        return counts

    theme_migration.prune_retired_pins(services)

    skill_journal_task = asyncio.create_task(_recover_skill_updates())
    app.state.skill_journal_recovery = skill_journal_task

    auto_update_hook = after_refresh_hook(services)

    async def _after_index_refresh() -> None:
        await auto_update_hook()
        from src.core.pack.skills.wiring import after_index_refresh as _pack_skills_after_refresh

        await _pack_skills_after_refresh()

    services.catalog.index_cache.after_refresh = _after_index_refresh

    async def _boot_auto_update() -> None:
        await asyncio.wait({skill_journal_task})
        await run_required_pass(app)
        await run_adoption_pass(services)
        await run_catalog_move_pass(services, settings.get_state_dir())
        await run_auto_update_pass(services)

    catalog_index_refresher = IndexRefresher(services.catalog.index_cache, services=services)
    catalog_index_refresher.start()
    app.state.catalog_index_refresher = catalog_index_refresher

    skill_auto_update_task = asyncio.create_task(_boot_auto_update())
    app.state.skill_auto_update = skill_auto_update_task

    auto_sleep_clock = IdleClock()
    mac_awake_guard = MacAwakeGuard()
    app.state.mac_awake_guard = mac_awake_guard
    await asyncio.to_thread(
        reconcile_mac_awake_at_boot, mac_awake_guard, Path(settings.auth_config_file).expanduser()
    )
    from src.core.crosstalk.delivery.dispatcher import Dispatcher
    app.state.crosstalk_dispatcher = Dispatcher(app) if datastore_state.healthy else None
    if app.state.crosstalk_dispatcher is not None:
        await app.state.crosstalk_dispatcher.start()
    from src.core.messaging import runtime as messaging_runtime
    app.state.messaging = None
    messaging_installed = await messaging_runtime.install(app) if datastore_state.healthy else None
    from src.core.session_token_usage import reader_state
    await asyncio.to_thread(reader_state.install, settings.get_state_dir())
    from src.core.mcp.approvals import runtime as approval_runtime
    await approval_runtime.install(app)
    attention_watcher = build_attention_watcher(
        session_manager,
        app_state=app.state,
        broadcast=connection_manager.broadcast_to_session,
        idle_clock=auto_sleep_clock,
    )
    app.state.attention_watcher = attention_watcher
    attention_watcher_task = asyncio.create_task(attention_watcher.run())
    from src.core.notifications.sources import lifecycle as notify_sources

    notify_sources_task = notify_sources.start(app.state, asyncio.get_running_loop())
    from src.api.session_listing_collections import listing_collections
    from src.core.listing_push.publisher import ListingPublisher

    from src.core.resource_push.client_build import ClientBuildWatch
    from src.core.static_asset_keys import client_build_key

    listing_publisher = ListingPublisher(
        listing_collections(app.state), app.state.event_hub.publish,
        lambda: app.state.event_hub.client_count,
        after_pass=ClientBuildWatch(client_build_key).check,
    )
    app.state.event_hub.add_listener(listing_publisher.on_hub_publish)
    app.state.listing_publisher = listing_publisher
    resource_push.add_topic_listener(resource_topics.AUTOMATIONS, listing_publisher.wake)
    listing_publisher_task = asyncio.create_task(listing_publisher.run())
    auto_sleeper = AutoSleeper(
        app.state, auto_sleep_clock,
        sleep=lambda session_uuid: auto_sleep_by_uuid(app.state, session_uuid),
    )
    app.state.auto_sleeper = auto_sleeper
    auto_sleep_task = asyncio.create_task(auto_sleeper.run())
    from src.core.mcp_bridge.migration.migrator import BridgeMigrator

    app.state.mcp_bridge_migrator = BridgeMigrator(app.state.session_manager)
    bridge_migration_task = asyncio.create_task(app.state.mcp_bridge_migrator.run(
        getattr(app.state.session_manager, "_boot_readopt_task", None)))
    automation_scheduler.start(app.state, settings.get_state_dir())
    automation_wiring.register(settings.get_state_dir())
    automation_seed.apply(app.state.automation_store)
    automation_seed_backup.apply(app.state.automation_store)
    logger.info(
        "attention_watcher_scheduled",
        tick_seconds=attention_watcher.tick_seconds,
    )
    from src.core.db import db_path_for as _work_db_path
    from src.core.session_work_backfill import run_boot_backfill

    work_backfill_task = asyncio.create_task(asyncio.to_thread(
        run_boot_backfill, _work_db_path(settings.get_state_dir())
    ))

    update_checker = UpdateChecker(
        config_path=Path(settings.auth_config_file).expanduser(),
    )
    set_update_checker(update_checker)
    app.state.update_checker = update_checker
    update_checker.start()

    try:
        provider_ledger_poller.start(app.state)
    except Exception as exc:
        logger.warning("provider_ledger_poller_start_failed", error=str(exc))

    # PRAGMA integrity_check
    db_integrity_scheduler = DatabaseIntegrityScheduler(
        settings.get_state_dir()
    )
    try:
        db_integrity_scheduler.start()
    except Exception as exc:
        logger.warning("db_integrity_scheduler_start_failed", error=str(exc))
    app.state.db_integrity_scheduler = db_integrity_scheduler

    session_journal_scheduler = None
    try:
        from src.core.db import db_path_for as _journal_db_path
        from src.core.tmux_backend import DEFAULT_SOCKET_NAME as _journal_default_socket

        try:
            _journal_socket = settings.load_auth_config().session.tmux_socket_name
        except (OSError, ValueError, AttributeError):
            _journal_socket = _journal_default_socket
        session_journal_scheduler = SessionJournalScheduler(
            settings.get_state_dir(), settings, _journal_socket,
            _journal_db_path(settings.get_state_dir()),
        )
        session_journal_scheduler.start()
    except Exception as exc:
        logger.warning("session_journal_start_failed", error=str(exc))
    app.state.session_journal_scheduler = session_journal_scheduler

    # CLOUDE_TEST_MODE
    try:
        if os.environ.get("CLOUDE_TEST_MODE") != "1":
            from src.core.db import db_path_for as _lineage_db_path
            from src.core.lineage import live as _lineage_live

            _lineage_live.start(_lineage_db_path(settings.get_state_dir()), settings.get_state_dir())
    except (OSError, RuntimeError) as exc:
        logger.warning("lineage_live_start_failed", error=str(exc))

    from src.core.stats.wiring import start_stats
    await start_stats(app.state, session_manager, settings.get_state_dir(),
                      Path(settings.auth_config_file).expanduser())

    live_log_level.announce(logger, "application_ready")
    logger.info(
        "server_ready_local_only",
        host=settings.host,
        port=settings.port,
    )

    try:
        from src.core.federation.discovery import Discovery, testslot_instance_name
        from src.core.message_host_identity import _ioreg_platform_uuid

        from src.core.computers import runtime as _computers_runtime
        from src.core.federation.fed_key import local_fid

        _platform_uuid = await asyncio.to_thread(_ioreg_platform_uuid)
        _federation_fid = await asyncio.to_thread(local_fid, settings.get_state_dir())
        _slot_name = testslot_instance_name(os.environ)
        federation_discovery = Discovery(
            config_path=Path(settings.auth_config_file).expanduser(),
            fid_provider=lambda: _computers_runtime.advertised_fid() or _federation_fid,
            platform_uuid_provider=lambda: _platform_uuid,
            link_port_provider=_computers_runtime.advertised_link_port,
            advertise_allowed=not os.environ.get("CARNIVORE_SETTINGS_ENV_FILE") or _slot_name is not None,
            **({"name_provider": lambda: _slot_name} if _slot_name else {}),
        )
        app.state.federation_discovery = federation_discovery
    except Exception as exc:
        federation_discovery = None
        logger.warning("federation_discovery_start_failed", error=str(exc))

    from src.core.skill_manager import card_art as _skill_card_art

    _skill_card_art.register_feature()
    from src.core.skill_manager import card_summary as _skill_card_summary

    _skill_card_summary.register_feature()
    from src.core.automations import schedule_nl as _automations_schedule_nl

    _automations_schedule_nl.register_feature()
    from src.api.skill_card_art_backfill import queue_missing as _queue_card_art

    app.state.card_art_backfill = asyncio.create_task(_queue_card_art(app))

    federation_listener = federation_pair_socket = federation_events_task = notification_sync_task = pack_machines_task = pack_maintain_task = None
    computers_rt = None
    try:
        from src.api import peer_auth as _peer_auth
        from src.core.federation import peer_links as _peer_links
        from src.core.federation.peer_listener import PeerListener, socket_path_for
        from src.core.hosts.ssh_master import default_instance_tag

        _fed_dir = Path.home() / ".carnivore" / "fed"
        federation_listener = PeerListener(app, socket_path_for(_fed_dir, default_instance_tag()))
        await federation_listener.start()
        from src.core.federation.pair_socket import PairSocket

        federation_pair_socket = PairSocket(str(_fed_dir / f"pair-{default_instance_tag()}.sock"),
                                            settings.get_state_dir())
        await federation_pair_socket.start()
        _peer_links.LINKS = _peer_links.PeerLinks(open_db=_peer_auth.open_db, listener_path=federation_listener.path)
        from src.api.door_auth import door_login_tokens, door_totp_ok
        from src.core.computers.runtime import ComputersRuntime, LazyPack
        from src.core.computers.this_label import this_label as _fed_label
        from src.core import version as _version
        from src.core.pack.machines import runtime as _pack_machines
        from src.core.stats import rollup as _stats_rollup

        door_file_name = f"door-{default_instance_tag()}.sock"
        app.state.door_file_name = door_file_name
        computers_rt = ComputersRuntime(
            open_db=_peer_auth.open_db, pack=LazyPack(_pack_machines.wiring), fed_dir=_fed_dir,
            listener_path=federation_listener.path, config_path=Path(settings.auth_config_file).expanduser(),
            host=settings.host, label=_fed_label(), app_version=_version.resolve_version(),
            door_path=str(_fed_dir / door_file_name), door_totp_ok=door_totp_ok,
            door_login=door_login_tokens, refresh_store=lambda: app.state.refresh_store,
            setup_status=lambda: current_setup_state().status,
            discovery=lambda: getattr(app.state, "federation_discovery", None), notify=resource_push.notify)
        await computers_rt.prepare(_peer_links.LINKS)
        await _peer_links.LINKS.boot()
        from src.core.federation import peer_events as _peer_events

        federation_events_task = asyncio.create_task(_peer_events.run(app.state, _peer_auth.open_db),
                                                     name="federation-peer-events")
        from src.core.notifications.sync import runtime as _notify_sync

        notification_sync_task = _notify_sync.start(app.state, _peer_auth.open_db)
        pack_machines_task = _pack_machines.start(
            _peer_auth.open_db, lambda: _peer_links.LINKS, label=_fed_label(), app_version=_version.resolve_version(),
            state_dir=lambda: str(settings.get_state_dir()),
            pipeline_rev=lambda: _stats_rollup.advertised_revisions(getattr(app.state, "stats_store", None)))
        from src.core.pack.relay import runtime as _pack_relay

        _pack_relay.start(_peer_auth.open_db, lambda: _peer_links.LINKS)
        from src.core.pack.skills import wiring as _pack_skills

        from src.core.pack.skills.watch import raise_open_file_limit as _raise_nofile

        _raise_nofile()
        _pack_skills.start(lambda: _peer_links.LINKS, services)
        from src.core.pack.placement import enhanced as _pack_placement_ai, maintain as _pack_maintain

        _pack_placement_ai.register_feature()
        pack_maintain_task = _pack_maintain.start(app, _pack_machines.wiring())
        from src.api import pack_copy_sync as _pack_copy_sync

        _pack_copy_sync.subscribe(app.state)
        await computers_rt.start()
    except Exception as exc:
        logger.warning("federation_link_start_failed", error=str(exc))

    from src.cplugs.host import runtime as cplugs_host

    _cplug_host = cplugs_host.install(app, settings.get_state_dir())
    from src.cplugs.host.legacy_disabled import import_disabled_plugins

    import_disabled_plugins(
        _cplug_host.state_dir,
        app.state.ui_preferences_store.read()["values"].get("disabled_plugins") or [],
        {d.id: d.manifest for d in cplugs_host.definitions()},
    )
    from src.core.approvals import beast_grid_migration, beast_lifecycle
    from src.cplugs.host.state import StateWriteFailed

    beast_grid_migration.migrate(_cplug_host.state_dir, Path(settings.auth_config_file).expanduser())
    beast_lifecycle.start(_cplug_host.state_dir)
    from src.core.crosstalk import card_prefs_migration

    card_prefs_migration.migrate(_cplug_host.state_dir, app.state.ui_preferences_store)
    from src.cplugs.host.split_migration import migrate as migrate_split_plugins

    try:
        migrate_split_plugins(_cplug_host.state_dir, Path(settings.auth_config_file).expanduser(),
                              datastore_state.fresh_install)
    except (OSError, ValueError) as exc:
        logger.error("cplug_split_migration_failed", error=f"{type(exc).__name__}: {exc}")
    from src.cplugs.host.vault_location_migration import migrate as migrate_vault_location

    try:
        migrate_vault_location(_cplug_host.state_dir, Path(settings.auth_config_file).expanduser())
    except StateWriteFailed as exc:
        logger.error("vault_location_migration_failed", error=f"{type(exc).__name__}: {exc}")
    from src.cplugs.host.swarm_default_migration import migrate as migrate_swarm_default

    try:
        migrate_swarm_default(_cplug_host.state_dir, datastore_state.fresh_install)
    except StateWriteFailed as exc:
        logger.error("cplug_swarm_default_migration_failed", error=f"{type(exc).__name__}: {exc}")
    from src.cplugs.host.plugin_fold import migrate as migrate_folded_plugins

    try:
        migrate_folded_plugins(_cplug_host.state_dir)
    except StateWriteFailed as exc:
        logger.error("cplug_fold_migration_failed", error=f"{type(exc).__name__}: {exc}")
    await _cplug_host.start()
    from src.cplugs.host import sidecar_boot

    app.state.sidecar_runtime = await sidecar_boot.boot(_cplug_host, app, asyncio.get_running_loop())
    catalog_index_refresher.after_pass = app.state.sidecar_runtime.index.sync
    catalog_index_refresher.hourly_while = app.state.sidecar_runtime.index.third_party_enabled
    from src.core.crosstalk import card_push as crosstalk_card_push

    crosstalk_card_push.install(
        app.state.event_hub.publish, asyncio.get_running_loop(), app.state.ui_preferences_store.read,
    )

    from src.core.perf_hooks import gc_tuning

    gc_tuning.tune_after_startup()

    yield

    logger.info("application_shutting_down")
    await app.state.sidecar_runtime.stop()
    await cplugs_host.host_for(app).stop()
    beast_lifecycle.stop(_cplug_host.state_dir)
    crosstalk_card_push.uninstall()

    if computers_rt is not None:
        await computers_rt.stop()
    if pack_maintain_task is not None:
        pack_maintain_task.cancel()
    from src.api import pack_copy_sync as _pack_copy_sync_stop

    _pack_copy_sync_stop.unsubscribe()
    if pack_machines_task is not None:
        pack_machines_task.cancel()
    if notification_sync_task is not None:
        notification_sync_task.cancel()
    if federation_events_task is not None:
        federation_events_task.cancel()
        from src.core.federation import peer_event_stream as _peer_event_stream

        await _peer_event_stream.stop()
    if federation_listener is not None:
        from src.core.federation import peer_links as _peer_links

        if _peer_links.LINKS is not None:
            await _peer_links.LINKS.shutdown()
            _peer_links.LINKS = None
        await federation_listener.stop()
        if federation_pair_socket is not None:
            await federation_pair_socket.stop()

    if federation_discovery is not None:
        federation_discovery.stop()

    update_checker.stop()
    try:
        from src.core.lineage import live as _lineage_live_stop

        _lineage_live_stop.stop()
    except RuntimeError as exc:
        logger.warning("lineage_live_stop_failed", error=str(exc))
    from src.core.account_notice import runner as account_notice_unwire

    account_notice_unwire.uninstall()
    from src.core.self_check import monitor as self_check_unwire

    self_check_unwire.uninstall()
    from src.core.transcript_manifest import condition as transcript_manifest_unwire

    transcript_manifest_unwire.uninstall()
    from src.core.app_alerts import wiring as app_alerts_unwire

    app_alerts_unwire.uninstall()
    from src.core.pipeline import wiring as pipeline_unwire

    pipeline_unwire.uninstall()
    deepsearch_index_scope.uninstall()
    set_update_checker(None)

    from src.core.stats.wiring import stop_stats
    await stop_stats(app.state)

    try:
        await provider_ledger_poller.stop()
    except Exception as exc:
        logger.warning("provider_ledger_poller_stop_failed", error=str(exc))

    try:
        await db_integrity_scheduler.aclose()
    except Exception as exc:
        logger.warning("db_integrity_scheduler_stop_failed", error=str(exc))
    if session_journal_scheduler is not None:
        try:
            await session_journal_scheduler.aclose()
        except Exception as exc:
            logger.warning("session_journal_stop_failed", error=str(exc))

    auto_sleep_task.cancel()
    with suppress(asyncio.CancelledError):
        await auto_sleep_task
    bridge_migration_task.cancel()
    with suppress(asyncio.CancelledError):
        await bridge_migration_task
    logger.info("auto_sleep_stopped")
    await automation_scheduler.stop()
    await catalog_index_refresher.stop()

    try:
        await asyncio.to_thread(mac_awake_guard.reconcile, 0)
    except Exception as exc:
        logger.warning("mac_awake_shutdown_failed", error=str(exc))

    git_status_watch = getattr(app.state, "git_status_watch", None)
    if git_status_watch is not None:
        await git_status_watch.stop()
    session_tasks_watch = getattr(app.state, "session_tasks_watch", None)
    if session_tasks_watch is not None:
        await session_tasks_watch.stop()
    machine_stats_watch = getattr(app.state, "machine_stats_watch", None)
    if machine_stats_watch is not None:
        await machine_stats_watch.stop()
    server_log_watch = getattr(app.state, "server_log_watch", None)
    if server_log_watch is not None:
        await server_log_watch.stop()
    stats_feed = getattr(app.state, "stats_feed", None)
    if stats_feed is not None:
        await stats_feed.stop()
    listing_publisher_task.cancel()
    resource_push.uninstall()
    with suppress(asyncio.CancelledError):
        await listing_publisher_task
    if app.state.crosstalk_dispatcher is not None:
        app.state.crosstalk_dispatcher.close()
    await messaging_runtime.uninstall(messaging_installed)
    attention_watcher_task.cancel()
    with suppress(asyncio.CancelledError):
        await attention_watcher_task
    await asyncio.to_thread(reader_state.stop)
    logger.info("attention_watcher_stopped")
    await notify_sources.stop(notify_sources_task)

    try:
        await session_manager.hosts.close_all()
    except (OSError, RuntimeError) as exc:
        logger.warning("remote_hosts_close_failed", error=str(exc))

    if upload_sweeper_task is not None:
        upload_sweeper_task.cancel()
        with suppress(asyncio.CancelledError):
            await upload_sweeper_task
        logger.info("upload_sweeper_stopped")

    if log_rotate_task is not None:
        log_rotate_task.cancel()
        with suppress(asyncio.CancelledError):
            await log_rotate_task
    pipe_pruner_task.cancel()
    with suppress(asyncio.CancelledError):
        await pipe_pruner_task
    skill_sweeper_task.cancel()
    with suppress(asyncio.CancelledError):
        await skill_sweeper_task
    logger.info("skill_sweeper_stopped")

    skill_journal_task.cancel()
    with suppress(asyncio.CancelledError):
        await skill_journal_task
    with suppress(asyncio.CancelledError):
        await work_backfill_task

    if _refresh_purge_task is not None:
        _refresh_purge_task.cancel()
        try:
            await _refresh_purge_task
        except (asyncio.CancelledError, Exception):
            pass
    if refresh_store is not None:
        await refresh_store.close()
    await phone_link_boot.stop(app)
    if getattr(app.state, "relay", None) is not None:
        await app.state.relay.aclose()
    if spectator_links_store is not None:
        await spectator_links_store.close()

    browser_sweep_task.cancel()
    with suppress(asyncio.CancelledError):
        await browser_sweep_task
    await browser_manager.aclose()

    await log_monitor.stop_monitoring()
    if local_servers is not None:
        await local_servers.stop()

    await notifications_install.uninstall(notifications_installed)

    from src.core.tmux_control.client import shutdown_all as control_input_shutdown
    await control_input_shutdown()

    await catalog_client.shutdown()

    logger.info("application_shutdown_complete")


app = FastAPI(
    title="☁️ Cloud Code",
    description="Remote control and monitoring for Claude Code sessions",
    version=resolve_version() or "unknown",
    lifespan=lifespan,
    dependencies=[Depends(peer_route_guard)],
)
app.add_exception_handler(PeerForwarded, lambda _request, exc: exc.response)
app.add_exception_handler(AccountRequired, account_required_handler)


_VALIDATION_ERROR_KEYS = ("loc", "msg", "type")


def _safe_validation_errors(errors: list) -> list:
    return [
        {key: entry[key] for key in _VALIDATION_ERROR_KEYS if key in entry}
        for entry in errors
        if isinstance(entry, dict)
    ]


@app.exception_handler(RequestValidationError)
async def _validation_error_as_400(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content=jsonable_encoder({"detail": _safe_validation_errors(exc.errors())}),
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info("CORS allowed origins", origins=settings.allowed_origins)


@app.middleware("http")
async def csp_headers(request: Request, call_next):
    response = await call_next(request)
    stamp_security_headers(response.headers, request.url.path)
    return response

app.state.limiter = auth_limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    HostGuardMiddleware,
    extra_hosts=settings.allowed_hosts_extra,
    allowed_origins=settings.allowed_origins,
)

app.add_middleware(JoinedLockdownMiddleware)

app.add_middleware(JsonGzipMiddleware)

app.add_middleware(RequestLogMiddleware)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(api_router, prefix="/api/v1")
app.include_router(config_files_router, prefix="/api/v1")
app.include_router(version_router, prefix="/api/v1")
phone_link_boot.include_routers(app)
app.include_router(status_router, prefix="/api/v1")
app.include_router(attention_router, prefix="/api/v1")
app.include_router(toast_router, prefix="/api/v1")
app.include_router(preferences_router, prefix="/api/v1")
app.include_router(widget_bars_router, prefix="/api/v1")
app.include_router(session_groups_router, prefix="/api/v1")
app.include_router(session_group_icon_router, prefix="/api/v1")
app.include_router(restore_offer_router, prefix="/api/v1")
app.include_router(restart_router, prefix="/api/v1")
app.include_router(setup_router, prefix="/api/v1")
app.include_router(setup_page_router)
app.include_router(mcp_router)
app.include_router(ws_router)
app.include_router(events_ws_router)
app.include_router(browser_ws_router)

client_dir = Path(__file__).parent.parent / "client"


class NoCacheStaticFiles(StaticFiles):

    _NO_CACHE_SUFFIXES = (".js", ".html", ".json", ".css")

    def _cache_control_for(self, path: str, scope: dict) -> str:
        query = scope.get("query_string", b"")
        if b"v=" not in query:
            return static_asset_keys.REVALIDATE
        requested = parse_qs(query.decode("latin-1")).get("v", [""])[0]
        candidate = static_asset_keys.url_to_path(
            static_asset_keys.STATIC_PREFIX + path, Path(self.directory)
        )
        return static_asset_keys.cache_control_for(candidate, requested)

    async def get_response(self, path, scope):
        keyed = keyed_page_response(path, scope, Path(self.directory))
        if keyed is not None:
            return keyed
        response = await super().get_response(path, scope)
        if path.lower().endswith(self._NO_CACHE_SUFFIXES):
            response.headers["Cache-Control"] = self._cache_control_for(path, scope)
            response = await maybe_gzip_file_response(response, scope)
        return response


app.mount("/static", NoCacheStaticFiles(directory=str(client_dir)), name="static")

_warmed_count = warm_static_gzip_cache(client_dir, NoCacheStaticFiles._NO_CACHE_SUFFIXES)
logger.info("static_gzip_cache_warmed", files=_warmed_count)

_keyed_assets = static_asset_keys.warm(client_dir, client_dir / "index.html")
logger.info("static_asset_keys_warmed", assets=_keyed_assets)


_VERSION_PLACEHOLDER = "{{VERSION}}"
_CLIENT_BUILD_PLACEHOLDER = "{{CLIENT_BUILD}}"

APP_VERSION = resolve_version()


def _render_index_html() -> str:
    html = (client_dir / "index.html").read_text(encoding="utf-8")
    chip = f"v{APP_VERSION}" if APP_VERSION else ""
    html = html.replace(_VERSION_PLACEHOLDER, chip).replace(
        _CLIENT_BUILD_PLACEHOLDER, static_asset_keys.client_build_key(client_dir)
    )
    return static_asset_keys.render(html, client_dir)


_INDEX_HTML_GZIP_CACHE_KEY = "index.html:rendered"


def _render_index_html_response(request: Request) -> Response:
    return render_compressible_html_response(
        request, _render_index_html, client_dir / "index.html",
        _INDEX_HTML_GZIP_CACHE_KEY,
        fingerprint=static_asset_keys.shell_fingerprint,
    )


user_themes_dir = theme_paths.user_themes_dir()
theme_migration.ensure_user_themes_dir()
if user_themes_dir.exists():
    app.mount(
        "/themes",
        NoCacheStaticFiles(directory=str(user_themes_dir), html=False),
        name="user-themes",
    )
    logger.info("user_themes_mount", path=str(user_themes_dir))
else:
    logger.info("user_themes_mount_skipped", path=str(user_themes_dir), reason="dir not present")


@app.get("/")
async def root(request: Request):
    """Serve the web interface."""
    return _render_index_html_response(request)


@app.get("/session/{project}")
async def session_deep_link(project: str, request: Request):
    """Serve the SPA shell for deep-link URLs.

    The ``project`` path parameter is consumed by the client-side router
    after the SPA boots; this handler does not inspect or validate it.
    """
    return _render_index_html_response(request)


@app.get("/layout/{layout_uuid}")
async def layout_deep_link(layout_uuid: str, request: Request):
    """Serve the SPA shell for a saved Layout (issue #424); the client resolves the uuid."""
    return _render_index_html_response(request)


@app.get("/session")
async def session_empty(request: Request):
    """Redirect a bare ``/session`` to the sessions view at ``/#sessions``."""
    return RedirectResponse(url="/#sessions", status_code=307)


@app.get("/archive")
async def archive_root_removed() -> RedirectResponse:
    """Send a visitor to the launchpad; the archive screen is gone.

    Output: RedirectResponse - 302 to "/".
    Example: GET /archive -> 302 Location: /
    """
    return RedirectResponse(url="/", status_code=302)


@app.get("/archive/{rest:path}")
async def archive_deep_link_removed(rest: str) -> RedirectResponse:
    """Send a deep-link visitor to the launchpad; the archive screen is gone.

    Inputs: rest (str) - the remainder of the archive path, ignored.
    Output: RedirectResponse - 302 to "/".
    Example: GET /archive/t/5767 -> 302 Location: /
    """
    return RedirectResponse(url="/", status_code=302)


@app.get("/api/v1/features")
async def features(_: str = Depends(require_auth)) -> JSONResponse:
    try:
        show_mark_unread = settings.load_auth_config().ui.show_mark_unread_control
    except (FileNotFoundError, OSError, ValueError) as exc:
        logger.warning("features_ui_flags_unreadable", error=str(exc))
        show_mark_unread = True
    return JSONResponse(content={"ui": {"show_mark_unread_control": show_mark_unread}})


_WEB_MANIFEST_PATH = client_dir / "manifest.webmanifest"
_APPLE_TOUCH_ICON_PATH = client_dir / "assets" / "icons" / "icon-180.png"
_SERVICE_WORKER_PATH = client_dir / "sw.js"


@app.get("/manifest.webmanifest")
async def web_manifest():
    """Serve the web app manifest from the origin root."""
    return FileResponse(
        _WEB_MANIFEST_PATH,
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.get("/sw.js")
async def push_service_worker():
    """Serve the push-only service worker from the origin root (issue #164). Never cached: a new worker must win."""
    return FileResponse(
        _SERVICE_WORKER_PATH,
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.get("/apple-touch-icon.png")
async def apple_touch_icon():
    """Serve the 180px home-screen icon for iOS's root-path probe."""
    return FileResponse(_APPLE_TOUCH_ICON_PATH, media_type="image/png")


@app.get("/health")
async def health_check():
    """Health check endpoint.

    Also reports the exposure in force, because the menu bar has to show the
    address the server is ACTUALLY on. Reading the configured value and
    displaying that would show an aspiration as a fact - the exact thing the
    bind lockdown makes possible, since a locked-down server is not on the
    address its own configuration names.

    This endpoint is unauthenticated, and reporting the bind here does not
    leak anything: whoever is reading the response already reached the socket.

    Returns:
        The usual health fields plus ``bind``: the effective and configured
        addresses, whether the lockdown is in force, and whether a restart is
        needed before the configured address applies.
    """
    setup_state = current_setup_state()
    return {
        "status": "healthy",
        "session_active": session_manager.health_summary() is not None if session_manager else False,
        "monitoring": log_monitor.is_monitoring if log_monitor else False,
        "setup_status": setup_state.status,
        "joined": setup_state.joined,
        "rebind_requested": membership.rebind_requested(),
        "door_file": getattr(app.state, "door_file_name", None),
        "bind": current_bind_report(),
    }


if __name__ == "__main__":
    import faulthandler

    import uvicorn

    faulthandler.enable(all_threads=True)

    # CLOUDE_DEV_RELOAD
    if settings.dev_reload:
        logger.warning(
            "dev_reload_enabled",
            note=(
                "uvicorn --reload is ON via CLOUDE_DEV_RELOAD=1. This "
                "process will restart itself whenever any watched file "
                "changes, including a git pull. Never set this in a "
                "deployed/production .env."
            ),
        )

    exposure = current_exposure()
    record_bound_host(exposure.bind_host)
    if exposure.locked_down:
        logger.warning(
            "bind_locked_down_pending_setup",
            configured_host=exposure.configured_bind_host,
            effective_host=exposure.bind_host,
            reason=exposure.reason,
        )
    else:
        logger.info(
            "bind_resolved",
            effective_host=exposure.bind_host,
            reason=exposure.reason,
        )

    log_redaction.install_stdlib_routing()

    if settings.dev_reload:
        uvicorn.run(
            "src.main:app",
            host=exposure.bind_host,
            port=settings.port,
            reload=settings.dev_reload,
            log_level="info",
            log_config=None,
            timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_S,
        )
    else:
        from src.core.early_listen import serve_early

        serve_early(uvicorn.Config(
            "src.main:app",
            host=exposure.bind_host,
            port=settings.port,
            log_level="info",
            log_config=None,
            timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_S,
        ))
