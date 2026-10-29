
from __future__ import annotations

import asyncio
import re
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import structlog

from src.core.hosts.identity import is_remote_backend, remote_session_id
from src.core.hosts.registry import HostUnavailable
from src.core.hosts.remote_host import RemoteHostUnavailable
from src.core.hosts.remote_listing import host_status_map, reconcile_host_rows

logger = structlog.get_logger()

ID_SOURCE_PANE_ENV = "pane_env"
ID_SOURCE_REMOTE_DERIVED = "remote_derived"

_SES_ID = re.compile(r"CLOUDECODE_SESSION_ID=(ses_[0-9a-f]{8})")

def default_delay(attempt: int) -> float:
    return float(min(60, 5 * 2 ** attempt))


def open_remote_hosts(connect: Callable[[], Optional[sqlite3.Connection]]) -> List[str]:
    from src.core.db_models import SESSION_LIFECYCLE_RUNNING

    try:
        conn = connect()
        if conn is None:
            return []
        with closing(conn):
            rows = conn.execute(
                "SELECT DISTINCT host_key FROM sessions WHERE host_key IN "
                "(SELECT key FROM hosts WHERE kind = 'ssh') "
                "AND lifecycle = ? AND archived_at IS NULL AND tmux_created_epoch IS NOT NULL",
                (SESSION_LIFECYCLE_RUNNING,)).fetchall()
    except (sqlite3.Error, OSError) as exc:
        logger.info("remote_readopt_hosts_unreadable", error=str(exc))
        return []
    return [str(row[0]) for row in rows]


def _plan(manager: Any, host: Any, listing: Any, held_ids: List[str],
          held_names: List[str]) -> Any:
    from src.core.session_boot_readopt_plan import plan_readopt
    from src.core.session_store import get_instance, sessions_table_ready

    conn = manager._datastore_connection()
    if conn is None:
        return None
    with closing(conn):
        if not sessions_table_ready(conn):
            return None
        return plan_readopt(
            listing_rows=listing.sessions,
            row_lookup=lambda name, epoch: get_instance(
                conn, socket=host.socket, name=name, epoch=epoch, host_key=host.host_key),
            hook_names={}, held_ids=held_ids, held_names=held_names,
            default_working_dir=host.home or "/")


async def _recovered_id(host: Any, name: str) -> Optional[str]:
    try:
        reply = await host.command("show-environment", "-t", f"={name}",
                                   "CLOUDECODE_SESSION_ID")
    except RemoteHostUnavailable:
        return None
    text = b"".join(reply.lines).decode("utf-8", errors="replace").strip()
    found = _SES_ID.fullmatch(text) if reply.ok else None
    return found.group(1) if found else None


async def readopt_on(manager: Any, host: Any) -> Dict[str, Any]:
    from src.core.session_backend import build_backend
    from src.core.session_boot_readopt_plan import session_for
    from src.core.tmux_listing import coerce_listing

    probe = build_backend(None, session_id="__readopt_probe__", working_dir=Path("/"),
                          on_output=None, remote_host=host)
    listing = coerce_listing(await asyncio.to_thread(probe.list_attachable_sessions))
    if not listing.ok:
        return {"outcome": "cannot_determine", "detail": listing.reason}
    status_map = await asyncio.to_thread(host_status_map, host)
    await asyncio.to_thread(reconcile_host_rows, manager, host.host_key, host.socket, status_map)
    registry = manager._registry
    held_names = [b.tmux_session for b in list(registry.backends.values())
                  if is_remote_backend(b) and b.host_key == host.host_key]
    plan = await asyncio.to_thread(_plan, manager, host, listing,
                                   list(registry.sessions.keys()), held_names)
    if plan is None:
        return {"outcome": "cannot_determine", "detail": "sessions table unavailable"}
    held, failed = [], []
    for target in plan.targets:
        session_id = await _recovered_id(host, target.name)
        source = ID_SOURCE_PANE_ENV
        if session_id is None or session_id in registry.sessions:
            session_id, source = remote_session_id(host.host_key, target.name), \
                ID_SOURCE_REMOTE_DERIVED
        if session_id in registry.sessions:
            continue
        target = replace(target, session_id=session_id, id_source=source)
        backend = build_backend(
            None, session_id=session_id, working_dir=Path(target.working_dir),
            on_output=manager._make_output_handler(session_id),
            viewer_probe=manager._make_viewer_probe(session_id), session_name=target.name,
            remote_host=host)
        try:
            await backend.attach_existing(needs_pipe_setup=True)
        except (RuntimeError, RemoteHostUnavailable, OSError) as exc:
            failed.append((target.name, str(exc)))
            logger.warning("remote_readopt_attach_failed", host=host.host_key,
                           session_id=session_id, error=str(exc))
            continue
        registry.register(session_for(target), backend)
        manager._instance_epochs[session_id] = target.epoch
        held.append((session_id, source))
    logger.info("remote_readopt_complete", host=host.host_key, held=len(held),
                failed=len(failed), skipped=len(plan.skipped))
    return {"outcome": "ran", "held": held, "failed": failed, "skipped": plan.skipped}


async def readopt_host(manager: Any, host_key: str, *,
                       delay: Callable[[int], float] = default_delay) -> Dict[str, Any]:
    attempt = 0
    while True:
        try:
            host = await manager.hosts.get(host_key)
            report = await readopt_on(manager, host)
        except HostUnavailable as exc:
            if exc.code != "host_unreachable":
                logger.info("remote_readopt_stopped", host=host_key, code=exc.code)
                return {"outcome": "stopped", "detail": exc.code}
            report = {"outcome": "cannot_determine", "detail": exc.code}
        except RemoteHostUnavailable as exc:
            report = {"outcome": "cannot_determine", "detail": str(exc)}
        if report["outcome"] == "ran":
            return report
        logger.info("remote_readopt_retry", host=host_key, attempt=attempt,
                    detail=report.get("detail"))
        await asyncio.sleep(delay(attempt))
        attempt += 1


async def readopt_remote_hosts(manager: Any, **options: Any) -> Dict[str, Dict[str, Any]]:
    keys = await asyncio.to_thread(open_remote_hosts, manager._datastore_connection)
    reports = await asyncio.gather(*(readopt_host(manager, key, **options) for key in keys))
    return dict(zip(keys, reports))


def schedule_remote_readopt(manager: Any) -> Optional["asyncio.Task[Any]"]:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    task = loop.create_task(readopt_remote_hosts(manager))
    manager.hosts.hold(task)
    return task
