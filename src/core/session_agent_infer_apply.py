
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence, Set, Tuple

import structlog

from src.core.claude_resume_argv import ProcessRow, list_process_table
from src.core.db_models import SESSION_FAMILY_SOURCE_LAUNCHED
from src.core.session_agent_infer import AgentInference, UNAVAILABLE
from src.core.session_agent_infer_families import infer_pane_agent
from src.core.hosts.ddl import LOCAL_HOST_KEY, host_scope

logger = structlog.get_logger()

APPLY_ALREADY_TRIED: str = "already_tried"

APPLY_ALREADY_RECORDED: str = "already_recorded"

APPLY_NO_INSTANCE: str = "no_instance"

APPLY_RAN: str = "ran"


@dataclass(frozen=True)
class InferApplyResult:

    outcome: str
    inference: Optional[AgentInference] = None
    written: bool = False


_TRIED: Set[Tuple[str, str, int]] = set()


def reset_memo() -> None:
    _TRIED.clear()


def read_process_table(
    *,
    table_reader: Callable[[], Optional[Sequence[ProcessRow]]] = list_process_table,
) -> Optional[Sequence[ProcessRow]]:
    try:
        return table_reader()
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_infer_process_table_failed", error=str(exc))
        return None


def _row_gate(
    conn: sqlite3.Connection, *, socket: str, name: str, epoch: int,
    host_key: str = LOCAL_HOST_KEY,
) -> Optional[str]:
    try:
        scope_sql, scope_params = host_scope(conn, host_key)
        row = conn.execute(
            "SELECT session_uuid, agent_type, agent_family_source "
            f"FROM sessions WHERE tmux_socket = ?{scope_sql} AND tmux_name = ? "
            "AND tmux_created_epoch = ?",
            (socket, *scope_params, name, int(epoch)),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning(
            "agent_infer_row_read_failed",
            tmux_name=name,
            error=str(exc),
            note="reported as no-instance; nothing is claimed about the pane",
        )
        return None
    if row is None:
        return None
    data = dict(row)
    if (data.get("agent_type") or "").strip():
        return None
    if (data.get("agent_family_source") or "") == SESSION_FAMILY_SOURCE_LAUNCHED:
        return None
    return str(data.get("session_uuid") or "") or None


def persist_inferred_agent_type(
    conn: sqlite3.Connection,
    *,
    session_uuid: str,
    agent_type: str,
    family_source: str,
    agent_family: str,
) -> bool:
    if not session_uuid or not agent_type or not family_source:
        return False
    try:
        cursor = conn.execute(
            "UPDATE sessions SET agent_type = ?, agent_family = ?, "
            "agent_family_source = ? WHERE session_uuid = ? "
            "AND (agent_type IS NULL OR agent_type = '') "
            "AND agent_family_source != ?",
            (
                agent_type,
                agent_family,
                family_source,
                session_uuid,
                SESSION_FAMILY_SOURCE_LAUNCHED,
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        logger.warning(
            "agent_infer_persist_failed",
            session_uuid=session_uuid,
            agent_type=agent_type,
            error=str(exc),
            note="best-effort write; hook delivery is unaffected",
        )
        return False
    return cursor.rowcount > 0


def configured_wrappers() -> Sequence:
    from src.config import wrapper_reader

    return wrapper_reader.configured_wrappers()


def apply_agent_inference(
    session_manager: Any,
    session_id: str,
    tmux_name: Optional[str],
    *,
    table_reader: Callable[[], Optional[Sequence[ProcessRow]]] = list_process_table,
    wrappers_reader: Callable[[], Sequence] = configured_wrappers,
) -> InferApplyResult:
    if not tmux_name:
        return InferApplyResult(APPLY_NO_INSTANCE)

    try:
        socket = session_manager.tmux_socket_name()
        epoch = getattr(session_manager, "_instance_epochs", {}).get(session_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_infer_identity_failed", error=str(exc))
        return InferApplyResult(APPLY_NO_INSTANCE)

    if epoch is None:
        return InferApplyResult(APPLY_NO_INSTANCE)

    key = (str(socket), str(tmux_name), int(epoch))
    if key in _TRIED:
        return InferApplyResult(APPLY_ALREADY_TRIED)

    conn = None
    try:
        conn = session_manager._writable_datastore_connection()
        if conn is None:
            return InferApplyResult(APPLY_NO_INSTANCE)

        session_uuid = _row_gate(conn, socket=str(socket), name=str(tmux_name), epoch=int(epoch))
        if session_uuid is None:
            _TRIED.add(key)
            return InferApplyResult(APPLY_ALREADY_RECORDED)

        _TRIED.add(key)

        from src.core.tmux_session_pane_pid import probe_session_pane_pid

        pane_pid = probe_session_pane_pid(str(tmux_name), socket=str(socket))
        verdict = infer_pane_agent(
            pane_pid=pane_pid,
            table=(
                read_process_table(table_reader=table_reader)
                if pane_pid is not None
                else None
            ),
            pane_current_command=_pane_current_command(session_manager, session_id),
            wrappers=wrappers_reader(),
        )
        inference = verdict.inference

        written = False
        if verdict.named:
            written = persist_inferred_agent_type(
                conn,
                session_uuid=session_uuid,
                agent_type=str(inference.agent_type),
                family_source=str(inference.family_source),
                agent_family=str(verdict.family),
            )
        logger.info(
            "agent_type_inferred",
            tmux_name=tmux_name,
            agent_family=verdict.family,
            outcome=inference.outcome,
            agent_type=inference.agent_type,
            candidates=list(inference.candidates),
            written=written,
            detail=inference.detail,
        )
        return InferApplyResult(APPLY_RAN, inference=inference, written=written)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "agent_infer_pass_failed",
            session_id=session_id,
            tmux_name=tmux_name,
            error=str(exc),
        )
        return InferApplyResult(APPLY_RAN, inference=UNAVAILABLE)
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:  # noqa: BLE001
                pass


def _pane_current_command(session_manager: Any, session_id: str) -> Optional[str]:
    backend = session_manager._registry.get_backend(session_id)
    value = getattr(backend, "pane_current_command", None) if backend else None
    return str(value) if value else None
