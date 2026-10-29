
from __future__ import annotations

import asyncio
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager, closing
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional

import structlog
from fastapi import HTTPException

from src.config import settings
from src.core import session_store
from src.core.companion_shell.ddl import COMPANION_OF_COLUMN
from src.core.db import connect, db_path_for
from src.core.db_models import SESSION_LIFECYCLE_STOPPED
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.hosts.identity import REMOTE_ID_PREFIX
from src.models import CompanionShell, CreateSessionRequest

logger = structlog.get_logger()

LIFECYCLE_SOURCE_CLOSED_WITH_AGENT = "closed_with_agent"
LIFECYCLE_SOURCE_CREATE_FAILED = "companion_create_failed"

PANE_LIVE, PANE_DEAD, PANE_UNKNOWN = "live", "dead", "unknown"

_LOCKS: Dict[int, list] = {}


def refuse(status: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail})


@asynccontextmanager
async def _agent_lock(agent_row: int) -> AsyncIterator[None]:
    entry = _LOCKS.setdefault(agent_row, [asyncio.Lock(), 0])
    entry[1] += 1
    try:
        async with entry[0]:
            yield
    finally:
        entry[1] -= 1
        if entry[1] == 0:
            _LOCKS.pop(agent_row, None)


@dataclass
class _Agent:

    session_id: str
    name: str
    socket: str
    row: Dict[str, Any]


def _connect() -> sqlite3.Connection:
    return connect(db_path_for(settings.get_state_dir()), create=False)


def _agent_row(name: str, socket: str, epoch: int) -> Optional[Dict[str, Any]]:
    with closing(_connect()) as conn:
        return session_store.get_instance(conn, socket=socket, name=name, epoch=epoch)


def _shell_row(agent_row: int) -> Optional[Dict[str, Any]]:
    with closing(_connect()) as conn:
        row = conn.execute(f"SELECT * FROM sessions WHERE {COMPANION_OF_COLUMN} = ?", (agent_row,)).fetchone()
        return dict(row) if row is not None else None


def _link(shell_row: int, agent_row: int) -> None:
    with closing(_connect()) as conn:
        conn.execute(f"UPDATE sessions SET {COMPANION_OF_COLUMN} = ? WHERE id = ?", (agent_row, shell_row))
        conn.commit()


def _mark_closed(shell_row: int) -> None:
    with closing(_connect()) as conn:
        conn.execute("UPDATE sessions SET lifecycle = ?, lifecycle_source = ? WHERE id = ?",
                     (SESSION_LIFECYCLE_STOPPED, LIFECYCLE_SOURCE_CREATE_FAILED, shell_row))
        conn.commit()


async def pane_state(name: str, socket: str) -> str:
    from pathlib import Path

    from src.core.tmux_backend import TmuxBackend

    probe = TmuxBackend.for_external(session_name=name, working_dir=Path.home(), on_output=None, socket_name=socket)
    dead = await probe.pane_dead_flag()
    return PANE_UNKNOWN if dead is None else PANE_DEAD if dead else PANE_LIVE


async def resolve_agent(app: Any, agent_id: str) -> _Agent:
    if agent_id.startswith(REMOTE_ID_PREFIX):
        raise refuse(409, "remote_agent", "the terminal widget works for agents on this computer")
    manager, index = app.state.session_manager, getattr(app.state, "companion_index", None)
    if index is None:
        raise refuse(503, "not_ready", "the companion shell index is not loaded yet")
    registry = manager._registry
    session, backend = registry.get_session(agent_id), registry.get_backend(agent_id)
    if session is None:
        if agent_id.startswith(("ses_", "adopted:")):
            raise refuse(409, "agent_not_running", "that agent is not running; its shell closed with it")
        raise refuse(404, "unknown_session", "no such session")
    if index.is_hidden_session(session):
        raise refuse(409, "is_a_shell", "that session is itself a companion shell")
    name, socket = getattr(session, "tmux_session", None), getattr(backend, "socket_name", None)
    epoch = await backend.session_created_epoch() if name and socket and backend is not None else None
    if epoch is None:
        raise refuse(409, "agent_not_running", "that agent is not running; its shell closed with it")
    row = await asyncio.to_thread(_agent_row, name, socket, epoch)
    if row is None:
        raise refuse(409, "agent_not_recorded", "that agent has no stored record to anchor a shell on")
    if (row.get("host_key") or LOCAL_HOST_KEY) != LOCAL_HOST_KEY:
        raise refuse(409, "remote_agent", "the terminal widget works for agents on this computer")
    folder = row.get("working_dir")
    if not folder or not os.path.isdir(folder):
        raise refuse(409, "folder_missing", "the agent's folder is not there")
    return _Agent(session_id=agent_id, name=name, socket=socket, row=row)


def _registered_shell(manager: Any, name: str) -> Optional[str]:
    ids = [sid for sid in manager._registry.registered_ids_for_tmux_name(name) if not sid.startswith(REMOTE_ID_PREFIX)]
    return ids[0] if ids else None


def _shaped(agent: _Agent, shell_row: Dict[str, Any], manager: Any, sid: str, state: str, pane: Optional[str]) -> CompanionShell:
    session = manager._registry.get_session(sid)
    return CompanionShell(
        agent_session_id=agent.session_id, agent_row_id=int(agent.row["id"]), session_id=sid,
        session_row_id=int(shell_row["id"]), tmux_session=getattr(session, "tmux_session", None) or shell_row.get("tmux_name"),
        working_dir=str(getattr(session, "working_dir", None) or shell_row.get("working_dir") or ""),
        state=state, pane=pane, session=session)


async def read(app: Any, agent_id: str) -> CompanionShell:
    agent = await resolve_agent(app, agent_id)
    shell = await asyncio.to_thread(_shell_row, int(agent.row["id"]))
    manager = app.state.session_manager
    sid = _registered_shell(manager, shell["tmux_name"]) if shell and shell.get("tmux_name") else None
    if shell is None or sid is None:
        raise refuse(404, "none", "this agent has no running shell")
    return _shaped(agent, shell, manager, sid, "existing", await pane_state(shell["tmux_name"], shell["tmux_socket"]))


async def ensure(request: Any, agent_id: str) -> CompanionShell:
    agent = await resolve_agent(request.app, agent_id)
    agent_row = int(agent.row["id"])
    async with _agent_lock(agent_row):
        shell = await asyncio.to_thread(_shell_row, agent_row)
        if shell is not None:
            return await _reopen(request, agent, shell)
        return await _create(request, agent)


async def _reopen(request: Any, agent: _Agent, shell: Dict[str, Any]) -> CompanionShell:
    manager = request.app.state.session_manager
    name, socket = shell.get("tmux_name"), shell.get("tmux_socket")
    sid = _registered_shell(manager, name) if name else None
    if sid is not None:
        pane = await pane_state(name, socket)
        if pane != PANE_DEAD:
            return _shaped(agent, shell, manager, sid, "existing", pane)
        try:
            result = await manager.respawn_session(name, socket_name=socket)
        except ValueError as exc:
            raise refuse(409, "shell_unavailable", str(exc))
        if not result.get("ok"):
            raise refuse(409, "shell_unavailable", str(result.get("detail") or "the shell could not be restarted"))
        return _shaped(agent, shell, manager, sid, "restarted", await pane_state(name, socket))
    from src.api.recreate_action import recreate_by_uuid

    resp = await recreate_by_uuid(str(shell["session_uuid"]), shell.get("agent_type") or "shell",
                                  get_manager=lambda: manager)
    if resp.status != "started" or not resp.session_id:
        raise refuse(409, "shell_unavailable", resp.detail or "the shell could not be restarted")
    new_name = resp.tmux_session or name
    request.app.state.companion_index.link(agent_row=int(agent.row["id"]), shell_row=int(shell["id"]), tmux_name=new_name)
    fresh = {**shell, "tmux_name": new_name}
    return _shaped(agent, fresh, manager, resp.session_id, "restarted", await pane_state(new_name, socket))


async def _create(request: Any, agent: _Agent) -> CompanionShell:
    from src.api.session_crud_routes import create_session_with_extra
    from src.core import session_sleep

    app, agent_row = request.app, int(agent.row["id"])
    manager, index = app.state.session_manager, app.state.companion_index
    sid = f"ses_{uuid.uuid4().hex[:8]}"
    index.reserve(sid)
    shell_name = shell_socket = None
    shell_row: Optional[int] = None
    try:
        body = CreateSessionRequest(
            working_dir=str(agent.row["working_dir"]), agent_type="shell", auto_start_claude=True,
            copy_templates=False, project_name=f"sh-{agent_row}")
        session = await create_session_with_extra(request, body, session_id=sid)
        shell_name = getattr(session, "tmux_session", None)
        shell_socket = getattr(manager._registry.get_backend(sid), "socket_name", None) or agent.socket
        identity = await asyncio.to_thread(manager._identity_for_instance, shell_name, getattr(session, "tmux_created_epoch", None))
        if not identity:
            raise RuntimeError("the new shell has no stored row")
        shell_row = int(identity["id"])
        await asyncio.to_thread(_link, shell_row, agent_row)
        index.link(agent_row=agent_row, shell_row=shell_row, tmux_name=shell_name)
    except BaseException:
        try:
            if shell_name:
                await session_sleep.close_for_sleep(manager, name=shell_name, socket=shell_socket)
            if shell_row is not None:
                await asyncio.to_thread(_mark_closed, shell_row)
        except Exception as exc:  # noqa: BLE001
            logger.warning("companion_create_cleanup_failed", agent_row=agent_row, error=type(exc).__name__)
        finally:
            index.release(sid)
        raise
    index.release(sid)
    shell = {"id": shell_row, "tmux_name": shell_name, "working_dir": str(agent.row["working_dir"])}
    return _shaped(agent, shell, manager, sid, "created", await pane_state(shell_name, shell_socket))
