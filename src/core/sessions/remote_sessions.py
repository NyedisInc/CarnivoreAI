
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import structlog

from src.core.hosts.identity import backend_host_key, is_remote_backend, parse_remote_session_id
from src.core.hosts.remote_listing import (  # noqa: F401
    gather_for, reap_remote, remote_session_info, snapshot_targets)
from src.core.hosts.remote_readopt import schedule_remote_readopt  # noqa: F401
from src.core.hosts.remote_resume import respawn_remote  # noqa: F401
from src.core.hosts.probe import AGENT_NAMES
from src.core.hosts.registry import HostUnavailable
from src.core.sessions.ports import SessionManagerSurface
from src.core.hosts.remote_host import RemoteHost, RemoteHostUnavailable
from src.core.hosts.ssh_exec import posix_quote
from src.models import Session, SessionStatus
from src.models.utc_time import utc_now

logger = structlog.get_logger()

DEFAULT_REMOTE_AGENT = "claude"

SHELL_FAMILY = "shell"

_PROBE_SESSION_ID = "__collision_probe__"


def _refuse_unsupported(unsupported: Mapping[str, Any]) -> None:
    for option, value in unsupported.items():
        if value:
            raise ValueError(f"{option} is not supported for a session on a remote host")


async def resolve_far_dir(host: RemoteHost, requested: Optional[str]) -> str:
    home = host.home or ""
    target = requested or home
    if target == "~" or target.startswith("~/"):
        target = home + target[1:]
    if not target.startswith("/") or any(ord(c) < 32 or ord(c) == 127 for c in target):
        raise ValueError(f"a folder on host {host.host_key} must be an absolute path")
    result = await host.exec(script=f"cd -- {posix_quote(target)} && pwd -P")
    lines = result.stdout_text.rstrip("\n").split("\n")
    if result.returncode != 0 or not lines[-1].startswith("/"):
        raise ValueError(f"{target} is not a folder on host {host.host_key}")
    return lines[-1]


def remote_command(agent_paths: Optional[Mapping[str, str]], host_key: str,
                   agent_type: Optional[str], label: Optional[str],
                   extra_args: Optional[List[str]]) -> tuple[Optional[str], str]:
    from src.core.claude_rename import launch_name_args_for_agent_type

    family = agent_type or DEFAULT_REMOTE_AGENT
    if family == SHELL_FAMILY:
        return None, family
    if family not in AGENT_NAMES:
        raise ValueError(f"on a remote host the agent is one of {', '.join(AGENT_NAMES)} or "
                         f"{SHELL_FAMILY}; "
                         f"{family!r} is a launch profile that runs on this machine")
    path = (agent_paths or {}).get(family)
    if not path:
        raise ValueError(f"{family} is not installed on host {host_key}; install it, then "
                         "probe the host again")
    words = [path, *launch_name_args_for_agent_type(label=label, agent_type=family),
             *(extra_args or [])]
    return " ".join(posix_quote(word) for word in words), family


def _names_on_host(manager: SessionManagerSurface, host_key: str) -> List[str]:
    return [backend.tmux_session for backend in list(manager._registry.backends.values())
            if is_remote_backend(backend) and backend.host_key == host_key]


async def _claim_name(manager: SessionManagerSurface, host: RemoteHost, base: Optional[str],
                      recreate: bool = False) -> Optional[str]:
    from src.core import session_backend, session_name_claim

    if base is None:
        return None
    probe = session_backend.build_backend(None, session_id=_PROBE_SESSION_ID,
                                          working_dir=Path("/"), on_output=None,
                                          remote_host=host)
    listing = await asyncio.to_thread(session_name_claim.probe_collision_listing, lambda: probe)
    claim = session_name_claim.claim_tmux_name(
        base, listing=listing, active_names=_names_on_host(manager, host.host_key),
        owned_names=(), recreate=recreate)
    return claim.name


def _persist(manager: SessionManagerSurface, backend: Any, *, far_dir: str, family: Optional[str],
             launched: bool, label: Optional[str], reuse_session_id: Optional[int]) -> Any:
    from src.core.db import transaction
    from src.core.session_create_persist import (
        CREATE_NO_DATASTORE,
        CreatePersistResult,
        persist_creation,
    )

    listing = backend.list_attachable_sessions()
    conn = manager._writable_datastore_connection()
    if conn is None:
        return CreatePersistResult(outcome=CREATE_NO_DATASTORE, detail="no datastore")
    try:
        with transaction(conn):
            return persist_creation(
                conn, socket=backend.host.socket, name=backend.tmux_session, listing=listing,
                working_dir=far_dir, agent_type=family, agent_family=family,
                agent_launched=launched, label=label, host_key=backend.host_key,
                reuse_session_id=reuse_session_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("remote_create_persist_failed", host=backend.host_key, error=str(exc))
        return CreatePersistResult(outcome=CREATE_NO_DATASTORE, detail=str(exc))
    finally:
        conn.close()


async def create_remote_session(
    manager: SessionManagerSurface, *, host_key: str, session_id: str, working_dir: Optional[str],
    auto_start: bool, initial_cols: Optional[int], initial_rows: Optional[int],
    base_name: Optional[str], agent_type: Optional[str], label: Optional[str],
    agent_extra_args: Optional[List[str]],
    unsupported: Mapping[str, Any], reuse_session_id: Optional[int] = None,
) -> Session:
    from src.core import session_backend

    _refuse_unsupported(unsupported)
    host = await manager.hosts.get(host_key)
    record = manager.hosts.record(host_key)
    command, family = (remote_command(record.agent_paths if record else None, host_key,
                                      agent_type, label, agent_extra_args)
                       if auto_start else (None, None))
    backend = None
    try:
        far_dir = await resolve_far_dir(host, working_dir)
        name = await _claim_name(manager, host, base_name, recreate=reuse_session_id is not None)
        backend = session_backend.build_backend(
            None, session_id=session_id, working_dir=Path(far_dir),
            on_output=manager._make_output_handler(session_id),
            viewer_probe=manager._make_viewer_probe(session_id), session_name=name,
            remote_host=host)
        await backend.start(command=command, env={"CLOUDECODE_SESSION_ID": session_id},
                            initial_cols=initial_cols, initial_rows=initial_rows)
    except RemoteHostUnavailable as exc:
        await manager._cleanup_failed_create(session_id, backend)
        raise HostUnavailable("host_unreachable", str(exc)) from exc
    except (ValueError, RuntimeError):
        await manager._cleanup_failed_create(session_id, backend)
        raise
    now = utc_now()
    session = Session(id=session_id, pty_pid=None, working_dir=far_dir,
                      status=SessionStatus.RUNNING, created_at=now, last_activity=now,
                      agent_type=family, tmux_session=backend.tmux_session)
    manager._registry.register(session, backend)
    persisted = await asyncio.to_thread(_persist, manager, backend, far_dir=far_dir,
                                        family=family, launched=auto_start, label=label,
                                        reuse_session_id=reuse_session_id)
    session.tmux_created_epoch = persisted.epoch
    if persisted.epoch is not None:
        manager._instance_epochs[session_id] = persisted.epoch
    logger.info("remote_session_created", session_id=session_id, host=host_key,
                origin_persist=persisted.outcome)
    return session


def host_fields(manager: SessionManagerSurface, backend: Any) -> Dict[str, str]:
    if not is_remote_backend(backend):
        return {}
    key = backend_host_key(backend)
    return {"host_key": key, "host_label": manager.hosts.label(key),
            "host_state": manager.hosts.state(key)}


def _parse(remote_id: str) -> tuple[str, str]:
    parsed = parse_remote_session_id(remote_id)
    if parsed is None:
        raise ValueError(f"{remote_id!r} is not a remote session id")
    return parsed


async def destroy_external(manager: SessionManagerSurface, remote_id: str) -> dict:
    host_key, name = _parse(remote_id)
    if name in _names_on_host(manager, host_key):
        raise ValueError(f"{remote_id!r} is a currently-active session; "
                         "use DELETE /sessions to destroy it")
    host = await manager.hosts.get(host_key)
    try:
        reply = await host.command("kill-session", "-t", f"={name}")
    except RemoteHostUnavailable as exc:
        raise HostUnavailable("host_unreachable", str(exc)) from exc
    text = b"".join(reply.lines).decode("utf-8", errors="replace").lower()
    logger.info("remote_external_session_destroy", host=host_key, killed=reply.ok)
    if reply.ok:
        return {"name": remote_id, "killed": True, "already_gone": False}
    if "can't find session" in text or "session not found" in text:
        return {"name": remote_id, "killed": False, "already_gone": True}
    raise RuntimeError(f"tmux kill-session on host {host_key} failed")


async def resolve_external_cwd(manager: SessionManagerSurface, remote_id: str) -> Path:
    host_key, name = _parse(remote_id)
    host = await manager.hosts.get(host_key)
    try:
        reply = await host.command("display-message", "-p", "-t", f"={name}:",
                                   "#{pane_current_path}")
    except RemoteHostUnavailable as exc:
        raise HostUnavailable("host_unreachable", str(exc)) from exc
    raw = b"".join(reply.lines).decode("utf-8", errors="replace").strip()
    return Path(raw if reply.ok and raw.startswith("/") else (host.home or "/"))
