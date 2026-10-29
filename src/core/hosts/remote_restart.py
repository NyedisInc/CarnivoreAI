
from __future__ import annotations

import asyncio
import sqlite3
import uuid as uuid_mod
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.core.hosts.probe import AGENT_NAMES

logger = structlog.get_logger()

ALREADY_RUNNING_CODE = "session_already_running"

# could not
HOST_UNMEASURED_CODE = "host_unmeasured"


class RemoteRestartRefused(Exception):

    def __init__(self, status: int, code: Optional[str], detail: str) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


async def preview_remote(manager: Any, remote_id: str) -> Any:
    """What restarting a live remote session would do, changing nothing.

    Inputs: manager (SessionManager); remote_id (str) - ``remote:<host>:<name>``.
    Output: RestartPreview - ``name`` echoes ``remote_id``.
    Raises: ValueError - malformed, or no such session registered on the host.
    Example: (await preview_remote(mgr, 'remote:hosta:carnivore_api')).unchanged.kind
    """
    from src.core.hosts.remote_resume import _row, remote_backend_for
    from src.core.session_respawn import resume_uuid_in
    from src.core.session_restart_preview import build_restart_preview
    from src.core.session_resume_target import resume_extra_args, resume_target_from_row
    from src.core.sessions.remote_sessions import remote_command

    session_id, backend = remote_backend_for(manager, remote_id)
    probe_ok, pane_dead, start_command = await backend.probe_respawn()
    row, read_ok = await asyncio.to_thread(_row, manager, backend,
                                           manager._instance_epochs.get(session_id))
    target = resume_target_from_row(row, row_read_ok=read_ok)
    resume_args = resume_extra_args(target)
    stored = (row or {}).get("agent_family") or (row or {}).get("agent_type")
    record = manager.hosts.record(backend.host_key)
    stored_command = None
    if stored in AGENT_NAMES:
        stored_command, _ = remote_command(record.agent_paths if record else None,
                                           backend.host_key, stored, None, resume_args)
    presence: Dict[str, tuple] = {}
    for candidate in (resume_uuid_in(start_command), target.claude_session_uuid):
        if candidate and candidate not in presence:
            presence[candidate] = await backend._resume_presence(candidate)
    logger.info("remote_restart_preview", host=backend.host_key, session_id=session_id,
                probe_ok=probe_ok, pane_dead=pane_dead, conversation=target.outcome)
    return build_restart_preview(
        name=remote_id, probe_ok=probe_ok, pane_dead=pane_dead,
        pane_start_command=start_command, stored_agent_type=stored,
        stored_agent_command=stored_command, offers=[], presence_by_uuid=presence,
        resume_outcome=target.outcome)


def _instance(manager: Any, session_uuid: str) -> Optional[dict]:
    conn = manager._writable_datastore_connection()
    if conn is None:
        return None
    with closing(conn):
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT id, tmux_name, tmux_created_epoch, lifecycle FROM sessions "
                           "WHERE session_uuid = ? LIMIT 1", (session_uuid,)).fetchone()
    return dict(row) if row is not None else None


async def _measure_gone(manager: Any, host: Any, name: str, epoch: Optional[int]) -> None:
    from src.core import session_backend, session_name_claim
    from src.core.session_adopt_persist import find_live_instance
    from src.core.session_recreate_presence import TMUX_GONE, TMUX_PRESENT, tmux_presence

    probe = session_backend.build_backend(None, session_id="__restart_probe__",
                                          working_dir=Path("/"), on_output=None,
                                          remote_host=host)
    listing = await asyncio.to_thread(session_name_claim.probe_collision_listing, lambda: probe)
    outcome = tmux_presence(name, listing_ok=listing.ok, listing_complete=listing.complete,
                            names=listing.names if listing.ok else None).outcome
    if outcome not in (TMUX_GONE, TMUX_PRESENT):
        raise RemoteRestartRefused(503, HOST_UNMEASURED_CODE,
                                   f"host {host.host_key} could not be measured, so whether "
                                   "this session is still running there is unknown; nothing "
                                   "was started")
    live = find_live_instance(listing, name) if outcome == TMUX_PRESENT else None
    created = (live or {}).get("created_at_epoch")
    same = live is not None and (epoch is None or created is None or int(created) == int(epoch))
    registered = any(getattr(b, "host_key", None) == host.host_key and b.tmux_session == name
                     for b in list(manager._registry.backends.values()))
    if same or registered:
        raise RemoteRestartRefused(409, ALREADY_RUNNING_CODE,
                                   "this session is already running")


async def restart_stopped(manager: Any, *, session_uuid: str, host_key: str,
                          source: Any) -> Dict[str, Any]:
    from src.core.hosts.remote_claude_files import far_transcript_presence
    from src.core.session_restart import RESTART_RESUMABLE, resume_arguments
    from src.core.sessions.remote_sessions import create_remote_session

    host = await manager.hosts.get(host_key)
    instance = await asyncio.to_thread(_instance, manager, session_uuid)
    name = (instance or {}).get("tmux_name")
    if not name:
        raise RemoteRestartRefused(404, None, "this row names no session on its host")
    await _measure_gone(manager, host, name, instance.get("tmux_created_epoch"))

    resumable = source.outcome == RESTART_RESUMABLE
    agent = source.agent_type if source.agent_type in AGENT_NAMES else None
    if resumable and agent == "claude":
        outcome, detail = await far_transcript_presence(host, source.claude_session_uuid)
        if outcome == "absent":
            logger.warning("remote_restart_refused_conversation_missing", host=host_key,
                           session_uuid=session_uuid)
            raise RemoteRestartRefused(409, None, detail)
    label = (source.title or "").strip() or None
    child = await create_remote_session(
        manager, host_key=host_key, session_id=f"ses_{uuid_mod.uuid4().hex[:8]}",
        working_dir=source.working_dir, auto_start=agent is not None, initial_cols=None,
        initial_rows=None, base_name=name, agent_type=agent, label=label,
        agent_extra_args=(resume_arguments(source.claude_session_uuid, family=agent)
                          if resumable and agent else None),
        unsupported={}, reuse_session_id=source.parent_id)
    after = await asyncio.to_thread(_instance, manager, session_uuid)
    reused = bool(after and after["tmux_name"] == child.tmux_session
                  and after["lifecycle"] == "running")
    logger.info("remote_restart_stopped", host=host_key, session_uuid=session_uuid,
                conversation="resumed" if resumable else "none_recorded", row_reused=reused)
    detail = None if resumable else source.detail
    if not reused:
        note = ("the session was restarted, but it could not keep its original record and "
                "now has a separate one")
        detail = f"{detail} {note}" if detail else note
    return {"success": True, "session": child.model_dump(),
            "conversation": "resumed" if resumable else "none_recorded",
            "replaced_session_id": source.parent_id, "row_reused": reused,
            "title_carried": label, "detail": detail}
