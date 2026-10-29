
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, Tuple

import structlog

from src.core.claude_resume_argv import ProcessRow, list_process_table
from src.core.session_agent_infer_apply import (
    _row_gate,
    configured_wrappers,
    persist_inferred_agent_type,
    read_process_table,
)
from src.core.session_agent_infer_families import infer_pane_agent

logger = structlog.get_logger()


def sweep_live_sessions(
    session_manager: Any,
    *,
    table_reader: Callable[[], Optional[Sequence[ProcessRow]]] = list_process_table,
    wrappers_reader: Callable[[], Sequence] = configured_wrappers,
) -> Tuple[int, int]:
    examined = 0
    written = 0
    conn = None
    try:
        rows = _live_pane_rows(session_manager)
        if not rows:
            return 0, 0
        socket = session_manager._tmux_socket_name()
        conn = session_manager._writable_datastore_connection()
        if conn is None:
            return 0, 0

        table = None
        wrappers = None
        for pane in rows:
            name = pane.get("name")
            epoch = pane.get("created_at_epoch")
            if not name or epoch is None:
                continue
            session_uuid = _row_gate(
                conn, socket=str(socket), name=str(name), epoch=int(epoch)
            )
            if session_uuid is None:
                continue
            examined += 1
            if table is None:
                table = read_process_table(table_reader=table_reader)
                wrappers = wrappers_reader()
            verdict = infer_pane_agent(
                pane_pid=pane.get("pid"),
                table=table,
                pane_current_command=pane.get("pane_current_command"),
                wrappers=wrappers or (),
            )
            inference = verdict.inference
            if verdict.named and persist_inferred_agent_type(
                conn,
                session_uuid=session_uuid,
                agent_type=str(inference.agent_type),
                family_source=str(inference.family_source),
                agent_family=str(verdict.family),
            ):
                written += 1
            logger.info(
                "agent_type_inferred",
                tmux_name=name,
                via="sweep",
                agent_family=verdict.family,
                outcome=inference.outcome,
                agent_type=inference.agent_type,
                candidates=list(inference.candidates),
                detail=inference.detail,
            )
        logger.info(
            "agent_infer_sweep_complete", examined=examined, written=written
        )
        return examined, written
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_infer_sweep_failed", error=str(exc))
        return examined, written
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:  # noqa: BLE001
                pass


def _live_pane_rows(session_manager: Any) -> Sequence[dict]:
    """One bulk tmux listing of every pane on the dedicated socket.

    Description: reuses ``TmuxBackend.list_pane_status_all``, which is
      already THE bulk pane read in this codebase and already returns the
      four fields the sweep needs. A listing that did not answer yields
      an empty sequence, which the sweep treats as "nothing measured" -
      never as "no panes".
    Inputs: session_manager (SessionManager).
    Output: Sequence[dict] - rows with ``name``, ``created_at_epoch``,
      ``pid`` and ``pane_current_command``.
    Example: _live_pane_rows(mgr)[0]['name']  # 'cloude_api'
    """
    from src.config import settings
    from src.core.session_backend import build_backend
    from src.core.tmux_listing import coerce_listing

    probe = build_backend(
        settings,
        session_id="__agent_infer_probe__",
        working_dir=Path.home(),
        on_output=None,
    )
    if not hasattr(probe, "list_pane_status_all"):
        return ()
    listing = coerce_listing(probe.list_pane_status_all())
    if not listing.ok:
        # did not answer
        logger.warning("agent_infer_sweep_listing_unavailable")
        return ()
    return listing.sessions or ()
