
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from typing import Any, Dict, Optional, Tuple

import structlog

from src.core.hosts.identity import is_remote_backend, parse_remote_session_id
from src.core.hosts.probe import AGENT_NAMES

logger = structlog.get_logger()


def remote_backend_for(manager: Any, remote_id: str) -> Tuple[str, Any]:
    parsed = parse_remote_session_id(remote_id)
    if parsed is None:
        raise ValueError(f"{remote_id!r} is not a remote session id")
    host_key, name = parsed
    for sid, backend in list(manager._registry.backends.items()):
        if is_remote_backend(backend) and backend.host_key == host_key \
                and backend.tmux_session == name:
            return sid, backend
    raise ValueError(f"no session named {name!r} is registered on host {host_key}")


def _row(manager: Any, backend: Any, epoch: Optional[int]) -> Tuple[Optional[Dict[str, Any]], bool]:
    from src.core.session_store import get_instance

    try:
        conn = manager._datastore_connection()
        if conn is None:
            return None, False
        with closing(conn):
            return get_instance(conn, socket=backend.socket_name, name=backend.tmux_session,
                                epoch=epoch, host_key=backend.host_key), True
    except (sqlite3.Error, OSError) as exc:
        logger.warning("remote_resume_row_unreadable", host=backend.host_key, error=str(exc))
        return None, False


async def respawn_remote(manager: Any, remote_id: str, *, agent_type: Optional[str] = None,
                         live_restart_confirmed: bool = False) -> dict:
    from src.core.session_resume_target import resume_extra_args, resume_target_from_row
    from src.core.attention.restart_floor import restart_bracket
    from src.core.sessions.remote_sessions import remote_command

    session_id, backend = remote_backend_for(manager, remote_id)
    if agent_type and agent_type not in AGENT_NAMES:
        raise ValueError(f"on a remote host the agent is one of {', '.join(AGENT_NAMES)}; "
                         f"{agent_type!r} is a launch profile that runs on this machine")
    epoch = manager._instance_epochs.get(session_id)
    row, read_ok = await asyncio.to_thread(_row, manager, backend, epoch)
    target = resume_target_from_row(row, row_read_ok=read_ok)
    resume_args = resume_extra_args(target)
    record = manager.hosts.record(backend.host_key)
    paths = record.agent_paths if record else None
    stored = (row or {}).get("agent_family") or (row or {}).get("agent_type")
    agent_command = chosen_command = None
    if stored in AGENT_NAMES:
        agent_command, _ = remote_command(paths, backend.host_key, stored, None, resume_args)
    if agent_type:
        chosen_command, _ = remote_command(paths, backend.host_key, agent_type, None, resume_args)
    logger.info("remote_respawn_request", host=backend.host_key, session_id=session_id,
                conversation=target.outcome, chosen=bool(chosen_command))
    with restart_bracket(manager._attention_watcher, backend, session_id) as window:
        result = await backend.respawn(
            agent_command=agent_command, chosen_agent_command=chosen_command,
            chosen_agent_type=agent_type if chosen_command else None,
            resume_outcome=target.outcome, live_restart_confirmed=bool(live_restart_confirmed))
        window.replaced = result.ok or bool(result.killed_live_pane)
    if result.epoch_before is not None and result.epoch_after not in (None, result.epoch_before):
        logger.warning("remote_respawn_epoch_moved", host=backend.host_key, session_id=session_id)
    return {
        "name": remote_id, "kind": result.kind, "ok": result.ok, "detail": result.detail,
        "command": result.command, "chosen": result.chosen,
        "agent_type": agent_type if chosen_command else None, "agent_type_persisted": False,
        "session_id": session_id, "session_uuid": (row or {}).get("session_uuid"),
        "killed_live_pane": bool(result.killed_live_pane), "identity_status": "unchecked",
        "conversation": result.conversation,
    }


def _bind_write(manager: Any, backend: Any, epoch: int, uuid: str, rebind: bool) -> int:
    from src.core.hosts.ddl import host_scope

    guard = ("claude_session_uuid IS NOT NULL AND claude_session_uuid != ?" if rebind
             else "claude_session_uuid IS NULL")
    try:
        conn = manager._writable_datastore_connection()
        if conn is None:
            return 0
        with closing(conn):
            scope_sql, scope_params = host_scope(conn, backend.host_key)
            cur = conn.execute(
                "UPDATE sessions SET claude_session_uuid = ? WHERE tmux_socket = ? "
                f"AND tmux_name = ? AND tmux_created_epoch = ?{scope_sql} AND {guard}",
                (uuid, backend.socket_name, backend.tmux_session, int(epoch), *scope_params,
                 *((uuid,) if rebind else ())))
            conn.commit()
            return cur.rowcount
    except (sqlite3.Error, OSError) as exc:
        logger.warning("remote_conversation_bind_failed", host=backend.host_key, error=str(exc))
        return 0


def bind_conversation(manager: Any, session_id: str, evidence: Any) -> Optional[str]:
    from src.core.attention.evidence import FAMILY_CODEX
    from src.core.attention.registry_read import STALE_CAUSE_CONVERSATION
    from src.core.hosts.remote_claude_files import files_for

    if getattr(evidence, "agent_family", None) == FAMILY_CODEX:
        from src.core.hosts.remote_codex_files import bind_codex_conversation

        return bind_codex_conversation(manager, session_id, evidence)
    backend = manager._registry.backends.get(session_id)
    registry = getattr(evidence, "registry", None)
    identity = getattr(evidence, "identity", None) or ()
    epoch = identity[2] if len(identity) > 2 else None
    if not is_remote_backend(backend) or registry is None or epoch is None:
        return None
    files = files_for(backend.host)
    if registry.known and registry.session_uuid:
        uuid, rebind = registry.session_uuid, False
    elif registry.stale_cause == STALE_CAUSE_CONVERSATION and registry.record_session_uuid:
        uuid, rebind = registry.record_session_uuid, True
        if files.transcript_present(uuid) is not True:
            return None
    else:
        return None
    key = (str(backend.tmux_session), int(epoch))
    if files.bound.get(key) == uuid:
        return None
    changed = _bind_write(manager, backend, epoch, uuid, rebind)
    files.bound[key] = uuid
    if changed:
        logger.info("remote_conversation_bound", host=backend.host_key, session_id=session_id,
                    rebind=rebind)
        return uuid
    return None
