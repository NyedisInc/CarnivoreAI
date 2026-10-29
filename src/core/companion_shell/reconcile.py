
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Set

import structlog

from src.config import settings
from src.core.companion_shell.close import close_shell, purge_row
from src.core.companion_shell.ddl import COMPANION_OF_COLUMN
from src.core.companion_shell.ensure import LIFECYCLE_SOURCE_CLOSED_WITH_AGENT, _agent_lock
from src.core.db import DatastoreError, connect, db_path_for
from src.core.db_models import (
    SESSION_LIFECYCLE_RUNNING,
    SESSION_LIFECYCLE_SOURCE_TMUX_LIST,
    SESSION_LIFECYCLE_SOURCE_TMUX_MISSING,
    SESSION_LIFECYCLE_STOPPED,
)
from src.core.hosts.identity import REMOTE_ID_PREFIX
from src.core.session_close_lifecycle import LIFECYCLE_SOURCE_CLOSED
from src.core.session_pane_death import LIFECYCLE_SOURCE_PANE_DEAD
from src.core.session_sleep import SLEEP_SOURCES

logger = structlog.get_logger()

KEEP, KEEP_UNKNOWN, CLOSE, PURGE = "keep", "keep_unknown_source", "close", "purge"

CLOSING_SOURCES: FrozenSet[str] = frozenset(
    SLEEP_SOURCES | {LIFECYCLE_SOURCE_CLOSED, SESSION_LIFECYCLE_SOURCE_TMUX_MISSING, SESSION_LIFECYCLE_SOURCE_TMUX_LIST})

_JOIN = (
    "SELECT s.id AS id, s.tmux_name AS tmux_name, s.tmux_socket AS tmux_socket, "
    f"s.{COMPANION_OF_COLUMN} AS companion_of, a.id AS a_id, a.tmux_name AS a_tmux_name, "
    "a.lifecycle AS a_lifecycle, a.lifecycle_source AS a_source, a.archived_at AS a_archived_at, "
    "s.lifecycle AS s_lifecycle, s.lifecycle_source AS s_source "
    f"FROM sessions s LEFT JOIN sessions a ON a.id = s.{COMPANION_OF_COLUMN} "
    f"WHERE s.{COMPANION_OF_COLUMN} IS NOT NULL")


@dataclass(frozen=True)
class Verdict:

    action: str
    reason: str


def decide(agent: Optional[Mapping[str, Any]], *, measured_gone: bool = False) -> Verdict:
    if agent is None:
        return Verdict(PURGE, "agent_row_gone")
    if measured_gone:
        return Verdict(CLOSE, "agent_tmux_gone")
    if agent.get("archived_at"):
        return Verdict(CLOSE, "agent_archived")
    lifecycle, source = agent.get("lifecycle"), agent.get("lifecycle_source")
    if lifecycle == SESSION_LIFECYCLE_RUNNING:
        return Verdict(KEEP, "agent_running")
    if lifecycle == SESSION_LIFECYCLE_STOPPED:
        if source in CLOSING_SOURCES:
            return Verdict(CLOSE, "agent_asleep_or_closed")
        if source == LIFECYCLE_SOURCE_PANE_DEAD:
            return Verdict(KEEP, "agent_pane_dead_husk")
        return Verdict(KEEP_UNKNOWN, "agent_stopped_unknown_source")
    return Verdict(KEEP_UNKNOWN, "agent_lifecycle_unmeasured")


def _read() -> List[Dict[str, Any]]:
    with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
        return [dict(r) for r in conn.execute(_JOIN)]


def _read_agent(agent_row: int) -> Optional[Dict[str, Any]]:
    with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
        found = conn.execute(
            "SELECT lifecycle, lifecycle_source, archived_at FROM sessions WHERE id = ?", (agent_row,)).fetchone()
        return dict(found) if found else None


def _registered(manager: Any, name: Optional[str]) -> bool:
    if not name:
        return False
    ids = manager._registry.registered_ids_for_tmux_name(name)
    return any(not sid.startswith(REMOTE_ID_PREFIX) for sid in ids)


async def _agent_tmux_gone(row: Mapping[str, Any]) -> bool:
    from src.api import recreate_routes as rr
    from src.core.session_recreate_presence import TMUX_GONE

    name = row.get("a_tmux_name")
    if not name:
        return False
    presence = await asyncio.to_thread(rr._measure_presence, name, row.get("tmux_socket") or rr._socket_name())
    return presence.outcome == TMUX_GONE


async def run_once(app: Any, gone_names: Iterable[str] = (), *, measure_agents: bool = False) -> int:
    manager, index = app.state.session_manager, app.state.companion_index
    gone = set(gone_names)
    if index.loaded and not index.tmux_names():
        return 0
    try:
        rows = await asyncio.to_thread(_read)
    except (DatastoreError, sqlite3.Error, OSError) as exc:
        logger.warning("companion_reconcile_unread", error=type(exc).__name__)
        return 0
    if not index.loaded:  # could not
        index.apply({int(r["companion_of"]): int(r["id"]) for r in rows},
                    {int(r["id"]): str(r["tmux_name"]) for r in rows if r["tmux_name"]})
    closed = 0
    for row in rows:
        registered = _registered(manager, row["tmux_name"])
        if row["a_id"] is None:
            async with _agent_lock(int(row["companion_of"])):
                if registered:
                    closed += bool(await close_shell(manager, index, row, purge=True,
                                                     local_servers=getattr(app.state, "local_servers", None)))
                else:
                    closed += bool(await purge_row(index, row))
            continue
        if not registered and (row["s_lifecycle"] == SESSION_LIFECYCLE_STOPPED
                               or row["s_source"] == LIFECYCLE_SOURCE_CLOSED_WITH_AGENT):
            continue
        agent = {"lifecycle": row["a_lifecycle"], "lifecycle_source": row["a_source"], "archived_at": row["a_archived_at"]}
        measured = bool(row["a_tmux_name"]) and row["a_tmux_name"] in gone
        if not measured and measure_agents and agent["lifecycle"] == SESSION_LIFECYCLE_RUNNING:
            measured = await _agent_tmux_gone(row)
        verdict = decide(agent, measured_gone=measured)
        if verdict.action == KEEP_UNKNOWN:
            logger.info("companion_kept_unknown_source", shell_row=row["id"], agent_row=row["companion_of"],
                        reason=verdict.reason, lifecycle=agent["lifecycle"], source=agent["lifecycle_source"])
        if verdict.action == CLOSE:
            async with _agent_lock(int(row["companion_of"])):
                try:
                    fresh = await asyncio.to_thread(_read_agent, int(row["companion_of"]))
                except (DatastoreError, sqlite3.Error, OSError) as exc:
                    logger.warning("companion_reconcile_unread", error=type(exc).__name__)
                    continue
                if fresh is None or decide(fresh, measured_gone=measured).action != CLOSE:
                    continue
                closed += bool(await close_shell(manager, index, row,
                                                 local_servers=getattr(app.state, "local_servers", None)))
    return closed


class Reconciler:

    def __init__(self, app: Any, loop: asyncio.AbstractEventLoop) -> None:
        self._app, self._loop = app, loop
        self._running, self._queued = False, False
        self._gone: Set[str] = set()
        self._measure = False
        self._task: Optional[asyncio.Task] = None
        self.runs = 0

    def request(self, gone_names: Iterable[str] = (), *, measure_agents: bool = False) -> None:
        self._loop.call_soon_threadsafe(self._kick, frozenset(gone_names), measure_agents)

    def _kick(self, gone: FrozenSet[str], measure_agents: bool = False) -> None:
        self._gone |= gone
        self._measure = self._measure or measure_agents
        if self._running:
            self._queued = True
            return
        self._running = True
        self._task = self._loop.create_task(self._drain())

    async def _drain(self) -> None:
        try:
            while True:
                gone, self._gone, self._queued = self._gone, set(), False
                measure, self._measure = self._measure, False
                self.runs += 1
                try:
                    await run_once(self._app, gone, measure_agents=measure)
                except (RuntimeError, OSError, sqlite3.Error, DatastoreError) as exc:
                    logger.warning("companion_reconcile_failed", error=type(exc).__name__)
                if not self._queued:
                    return
        finally:
            self._running = False


_active: Optional[Reconciler] = None


def install(app: Any, loop: asyncio.AbstractEventLoop) -> Reconciler:
    global _active
    _active = Reconciler(app, loop)
    return _active


def request(gone_names: Iterable[str] = (), *, measure_agents: bool = False) -> None:
    rec = _active
    if rec is None:
        return
    index = getattr(rec._app.state, "companion_index", None)
    if index is not None and index.loaded and not index.tmux_names():
        return
    rec.request(gone_names, measure_agents=measure_agents)


def request_when_done(task: Optional["asyncio.Future[Any]"]) -> None:
    if task is None or task.done():
        request(measure_agents=True)
    else:
        task.add_done_callback(lambda _t: request(measure_agents=True))


def on_hub_publish(frame_type: Optional[str]) -> None:
    if frame_type == "sessions.changed":
        request()
