
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable, Optional

import structlog

logger = structlog.get_logger()

RECOVERY_NOT_ATTEMPTED = "not_attempted"

RECOVERY_NO_MATCH = "no_match"

RECOVERY_BOUND = "bound"


def recover_claude_uuid(
    conn: sqlite3.Connection,
    *,
    socket: str,
    tmux_name: str,
    tmux_created_epoch: Optional[int],
    working_dir: Optional[str],
    pane_pid: Optional[int],
    projects_dir: Optional[Path] = None,
    process_table: Optional[list] = None,
    bind: Optional[Callable] = None,
) -> tuple:
    if not tmux_name:
        return (RECOVERY_NOT_ATTEMPTED, None)
    try:
        from src.core.claude_session_correlate_ladder import (
            correlate_adopted_session_ladder,
        )

        result = correlate_adopted_session_ladder(
            pane_pid=pane_pid,
            working_dir=working_dir,
            tmux_created_epoch=tmux_created_epoch,
            projects_dir=projects_dir,
            process_table=process_table,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "lineage_recovery_ladder_failed", tmux_name=tmux_name, error=str(exc)
        )
        return (RECOVERY_NO_MATCH, None)

    if not result.matched or not result.claude_session_uuid:
        logger.info(
            "lineage_recovery_abstained",
            tmux_name=tmux_name,
            outcome=result.outcome,
            detail=result.detail,
        )
        return (RECOVERY_NO_MATCH, None)

    try:
        if bind is None:
            from src.core.session_claude_correlate_bind import bind_correlated_uuid

            bind = bind_correlated_uuid
        from src.core.db_models import (
            SESSION_CLAUDE_UUID_SOURCE_CORRELATED,
            SESSION_CLAUDE_UUID_SOURCE_CORRELATED_ARGV,
        )
        from src.core.claude_session_correlate_ladder import LADDER_METHOD_PANE_ARGV

        source = (
            SESSION_CLAUDE_UUID_SOURCE_CORRELATED_ARGV
            if result.method == LADDER_METHOD_PANE_ARGV
            else SESSION_CLAUDE_UUID_SOURCE_CORRELATED
        )
        outcome = bind(
            conn,
            socket=socket,
            name=tmux_name,
            epoch=tmux_created_epoch,
            claude_uuid=result.claude_session_uuid,
            source=source,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "lineage_recovery_bind_failed", tmux_name=tmux_name, error=str(exc)
        )
        return (RECOVERY_NO_MATCH, None)

    if not getattr(outcome, "wrote", False):
        logger.info(
            "lineage_recovery_bind_declined",
            tmux_name=tmux_name,
            detail=getattr(outcome, "detail", None),
        )
        return (RECOVERY_NO_MATCH, None)

    logger.info(
        "lineage_recovered_without_hook",
        tmux_name=tmux_name,
        method=result.method,
        note="SessionStart delivered no session_id; recovered from evidence",
    )
    return (RECOVERY_BOUND, result.claude_session_uuid)
