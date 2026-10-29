
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from src.config import settings
from src.core.boot.steps import BootStep, FailureMode

if TYPE_CHECKING:
    from src.core.boot.context import BootContext
    from src.core.tmux_listing import TmuxListing

logger = structlog.get_logger()


def _migrate_projects(ctx: "BootContext") -> None:
    ctx.app.state.session_import_notice = None
    ctx.app.state.project_reconcile_notice = None
    if not ctx.datastore_state.healthy:
        return
    from src.core.projects_config_migration import migrate_projects_out_of_config

    _projects_migration = migrate_projects_out_of_config(
        settings.get_state_dir(),
        Path(settings.auth_config_file).expanduser(),
    )
    ctx.app.state.project_reconcile_notice = _projects_migration.notice()
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
            imported_undetermined=len(_projects_migration.imported_undetermined),
        )
    settings.drop_auth_config_cache()
    ctx.auth_cfg = settings.load_auth_config()


def _run_import(ctx: "BootContext") -> None:
    if not ctx.datastore_state.healthy:
        return
    from src.core.db import connect, db_path_for, transaction
    from src.core.session_import import run_first_run_import
    from src.core.session_stage_a_boundary import record_boundary
    from src.core.tmux_listing import coerce_listing
    from src.core.tmux_session_cwd import make_working_dir_probe

    session_manager = ctx.session_manager
    _listing = coerce_listing(session_manager.list_attachable_sessions())
    with closing(connect(db_path_for(settings.get_state_dir()))) as _import_conn:
        with transaction(_import_conn):
            record_boundary(_import_conn)
            _import_result = run_first_run_import(
                _import_conn,
                listing=_listing,
                owned_tmux_names=set(ctx.services.owned_tmux.names),
                socket=session_manager.tmux_socket_name(),
                working_dir_probe=make_working_dir_probe(
                    session_manager.tmux_socket_name()
                ),
                log_dir=settings.get_log_dir(),
            )
        ctx.app.state.session_import_notice = _import_result.home_screen_notice()
        logger.info(
            "first_run_import",
            outcome=_import_result.outcome,
            sessions_imported=_import_result.sessions_imported,
            listing_ok=_listing.ok,
            listing_reason=_listing.reason,
        )
        _backfill_attribution(ctx, _listing)


def _backfill_attribution(ctx: "BootContext", listing: "TmuxListing") -> None:
    from src.core.db import connect, db_path_for, transaction
    from src.core.session_attribution import backfill_attribution, live_instance_keys
    from src.core.session_project_binding import correct_shallow_derivations
    from src.core.tmux_session_cwd import make_working_dir_probe

    session_manager = ctx.session_manager
    _listing = listing
    with closing(connect(db_path_for(settings.get_state_dir()))) as _attr_conn:
        with transaction(_attr_conn):
            _rehomed = correct_shallow_derivations(_attr_conn)
            _attr_result = backfill_attribution(
                _attr_conn,
                working_dir_probe=make_working_dir_probe(session_manager.tmux_socket_name()),
                live_instances=live_instance_keys(session_manager.tmux_socket_name(), _listing),
            )
    logger.info(
        "session_attribution_backfill_boot",
        considered=_attr_result.considered,
        attributed_project=_attr_result.attributed_project,
        attributed_none=_attr_result.attributed_none,
        still_unknown=_attr_result.still_unknown,
        rehomed_to_deeper_project=_rehomed,
    )


def steps() -> list[BootStep]:
    return [
        BootStep(name="projects_config_migration", order=120, start=_migrate_projects),
        BootStep(name="first_run_import", order=130, start=_run_import, failure=FailureMode.DEGRADED,
                 degrades_on=(Exception,), failure_event="first_run_import_failed",
                 swallow_reason="the import must never block boot; a failed pass leaves the latch unset and retries next start"),
    ]
