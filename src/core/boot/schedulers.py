
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from src.api.version_routes import set_update_checker
from src.config import settings
from src.core.boot.steps import BootStep, FailureMode, teardown_slot
from src.core.db_integrity_task import DatabaseIntegrityScheduler
from src.core.log_level import live as live_log_level
from src.core.provider_ledger import poller as provider_ledger_poller
from src.core.session_journal_task import SessionJournalScheduler
from src.core.update_check import UpdateChecker

if TYPE_CHECKING:
    from src.core.boot.context import BootContext

logger = structlog.get_logger()

_SCHEDULER_SWALLOW = "a scheduler that cannot start must not stop boot; its route reports the named state"


def _start_update_checker(ctx: "BootContext") -> None:
    update_checker = UpdateChecker(config_path=Path(settings.auth_config_file).expanduser())
    set_update_checker(update_checker)
    ctx.app.state.update_checker = update_checker
    update_checker.start()


def _stop_update_checker(ctx: "BootContext") -> None:
    ctx.app.state.update_checker.stop()


def _clear_update_checker_route(_ctx: "BootContext") -> None:
    set_update_checker(None)


def _start_ledger(ctx: "BootContext") -> None:
    provider_ledger_poller.start(ctx.app.state)


async def _stop_ledger(_ctx: "BootContext") -> None:
    await provider_ledger_poller.stop()


def _build_integrity_scheduler(ctx: "BootContext") -> None:
    ctx.app.state.db_integrity_scheduler = DatabaseIntegrityScheduler(settings.get_state_dir())


def _start_integrity_scheduler(ctx: "BootContext") -> None:
    ctx.app.state.db_integrity_scheduler.start()


async def _stop_integrity_scheduler(ctx: "BootContext") -> None:
    await ctx.app.state.db_integrity_scheduler.aclose()


def _start_session_journal(ctx: "BootContext") -> None:
    from src.core.db import db_path_for as _journal_db_path
    from src.core.tmux_backend import DEFAULT_SOCKET_NAME as _journal_default_socket

    ctx.app.state.session_journal_scheduler = None
    try:
        _journal_socket = settings.load_auth_config().session.tmux_socket_name
    except (OSError, ValueError, AttributeError):
        _journal_socket = _journal_default_socket
    scheduler = SessionJournalScheduler(
        settings.get_state_dir(), settings, _journal_socket, _journal_db_path(settings.get_state_dir()),
    )
    ctx.app.state.session_journal_scheduler = scheduler
    scheduler.start()


async def _stop_session_journal(ctx: "BootContext") -> None:
    scheduler = getattr(ctx.app.state, "session_journal_scheduler", None)
    if scheduler is not None:
        await scheduler.aclose()


def _start_lineage(_ctx: "BootContext") -> None:
    if os.environ.get("CLOUDE_TEST_MODE") != "1":
        from src.core.db import db_path_for as _lineage_db_path
        from src.core.lineage import live as _lineage_live

        _lineage_live.start(_lineage_db_path(settings.get_state_dir()), settings.get_state_dir())


def _stop_lineage(_ctx: "BootContext") -> None:
    from src.core.lineage import live as _lineage_live_stop

    _lineage_live_stop.stop()


async def _start_stats(ctx: "BootContext") -> None:
    from src.core.stats.wiring import start_stats

    await start_stats(ctx.app.state, ctx.session_manager, settings.get_state_dir(),
                      Path(settings.auth_config_file).expanduser())


async def _stop_stats(ctx: "BootContext") -> None:
    from src.core.stats.wiring import stop_stats

    await stop_stats(ctx.app.state)


def _announce_ready(_ctx: "BootContext") -> None:
    live_log_level.announce(logger, "application_ready")
    logger.info("server_ready_local_only", host=settings.host, port=settings.port)


async def _close_engine_clients(ctx: "BootContext") -> None:
    from src.core.catalog import client as catalog_client
    from src.core.tmux_control.client import shutdown_all as control_input_shutdown
    from src.core.tmux_control.reader import close_readers

    await ctx.stop_part("control_input", control_input_shutdown)
    await ctx.stop_part("tmux_control_readers", close_readers)
    await ctx.stop_part("catalog_client", catalog_client.shutdown)


def steps() -> list[BootStep]:
    degraded = {"failure": FailureMode.DEGRADED, "degrades_on": (Exception,), "swallow_reason": _SCHEDULER_SWALLOW}
    return [
        BootStep(name="update_checker", order=550, start=_start_update_checker, stop=_stop_update_checker,
                 stop_order=teardown_slot(7)),
        BootStep(name="update_checker_route", order=551, stop_name="update_checker_unset", stop=_clear_update_checker_route, stop_order=teardown_slot(15)),
        BootStep(name="provider_ledger_poller", order=560, start=_start_ledger, stop=_stop_ledger,
                 failure_event="provider_ledger_poller_start_failed", stop_order=teardown_slot(17),
                 stop_after_failed_start=True, **degraded),
        BootStep(name="db_integrity_scheduler", order=570, start=_build_integrity_scheduler,
                 stop=_stop_integrity_scheduler, stop_order=teardown_slot(18)),
        BootStep(name="db_integrity_scheduler_start", order=571, start=_start_integrity_scheduler,
                 failure_event="db_integrity_scheduler_start_failed", **degraded),
        BootStep(name="session_journal", order=580, stop_name="session_journal_scheduler", start=_start_session_journal, stop=_stop_session_journal,
                 failure_event="session_journal_start_failed", stop_order=teardown_slot(19),
                 stop_after_failed_start=True, **degraded),
        BootStep(name="lineage_live", order=590, start=_start_lineage, stop=_stop_lineage,
                 failure=FailureMode.DEGRADED, degrades_on=(OSError, RuntimeError), failure_event="lineage_live_start_failed",
                 stop_order=teardown_slot(8), stop_after_failed_start=True),
        BootStep(name="stats", order=600, start=_start_stats, stop=_stop_stats, stop_order=teardown_slot(16)),
        BootStep(name="ready_announcement", order=610, start=_announce_ready),
        BootStep(name="engine_clients", order=700, stop_parts=("control_input", "tmux_control_readers", "catalog_client"), stop=_close_engine_clients, stop_order=teardown_slot(48)),
    ]
