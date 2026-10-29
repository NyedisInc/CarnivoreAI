"""Stamping the session listing with each session's Carnivore timers status (#1639, the row's timers icon and the stats bar).

The rule is ``src/core/automations/timer_status.py`` (one place); this module reads the store and the sessions table in ONE
off-loop pass per listing build, then COPIES the word onto the ``/sessions/list`` WRAPPER (gotcha 1). It never fails the listing.

NULL IS NOT "NONE". ``automations_state`` is ``none`` when the store was read and nothing is aimed at the session, and null
only when the store, the datastore or a registered plugin's schedules could not be read (or the row is a paired computer's,
which that computer stamps).
"""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import structlog

from src.config import settings
from src.core.automations import plugin_schedules, timer_status
from src.core.automations.timer_status import TimerStatus
from src.core.db import DatastoreUnreadableError
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.hosts.identity import REMOTE_ID_PREFIX
from src.models import SessionInfo
from src.models.sessions import ScheduledMark

logger = structlog.get_logger()


MAX_MARKS = 5


@dataclass(frozen=True)
class TimersSnapshot:

    pairs_by_row: Dict[int, list]
    overall: TimerStatus


def _row_ids(uuids: Iterable[str]) -> Dict[str, int]:
    from src.core.db import connect, db_path_for  # noqa: PLC0415

    wanted = sorted(set(uuids))
    path = db_path_for(settings.get_state_dir())
    if not wanted or not path.exists():
        return {}
    marks = ",".join("?" * len(wanted))
    with closing(connect(path, create=False)) as conn:
        return {r[1]: r[0] for r in conn.execute(f"SELECT id, session_uuid FROM sessions WHERE session_uuid IN ({marks})", wanted)}


def read_snapshot(store: Any) -> TimersSnapshot:
    automations = store.list_all()
    runs = store.latest_stopped_runs()
    per_uuid = timer_status.pairs_by_session(automations, runs)
    ids = _row_ids(per_uuid)
    return TimersSnapshot(pairs_by_row={ids[u]: pairs for u, pairs in per_uuid.items() if u in ids},
                          overall=timer_status.overall(automations, runs))


def global_status(store: Any, paused: bool) -> Dict[str, Any]:
    status = timer_status.overall(store.list_all(), store.latest_stopped_runs())
    if paused and status.total:
        status = TimerStatus(timer_status.DISABLED, status.total, status.enabled)
    return {"state": status.state, "total": status.total, "enabled": status.enabled}


def is_local(info: SessionInfo) -> bool:
    return not (info.host_key != LOCAL_HOST_KEY or str(info.session.id).startswith(REMOTE_ID_PREFIX) or info.origin_install_id is not None)


def scheduled_marks(pairs: Iterable[Any], entries: Iterable[Dict[str, Any]]) -> List[ScheduledMark]:
    marks = [ScheduledMark(name=str(a.get("name") or ""), enabled=bool(a.get("enabled")),
                           next_fire_at=a.get("next_fire_at") if a.get("enabled") else None) for a, _ in pairs]
    marks += [ScheduledMark(name=str(e.get("name") or ""), enabled=bool(e.get("enabled")),
                            next_fire_at=e.get("next_fire_at") if e.get("enabled") else None) for e in entries]
    marks.sort(key=lambda mark: (mark.next_fire_at is None, mark.next_fire_at or 0.0, mark.name.casefold()))
    return marks[:MAX_MARKS]


def _clear(info: SessionInfo) -> None:
    info.automations_state = info.automations_total = info.automations_enabled = info.automations_next = None


async def mark_automation_timers(app_state: Any, infos: Iterable[Any], asleep: Optional[List[Dict[str, Any]]] = None) -> None:
    store = getattr(app_state, "automation_store", None)
    owned = [i for i in infos if isinstance(i, SessionInfo) and is_local(i)]
    snapshot: Optional[TimersSnapshot] = None
    if store is not None:
        try:
            snapshot = await asyncio.to_thread(read_snapshot, store)
        except (OSError, sqlite3.Error, DatastoreUnreadableError) as exc:
            logger.warning("listing.automation_timers.unreadable", error=type(exc).__name__)
    schedules: Optional[Dict[str, List[Dict[str, Any]]]] = None
    if snapshot is not None:
        try:
            schedules = await plugin_schedules.read(owned, asleep)
        except plugin_schedules.PluginSchedulesUnreadable:
            schedules = None  # could not
    for info in owned:
        if snapshot is None or schedules is None:
            _clear(info)
            continue
        pairs = list(snapshot.pairs_by_row.get(info.session_row_id, ())) if info.session_row_id is not None else []
        entries = schedules.get(info.session.id, [])
        status = timer_status.roll_up(pairs + [timer_status.pair_of_schedule(e) for e in entries])
        info.automations_state, info.automations_total, info.automations_enabled = status.state, status.total, status.enabled
        info.automations_next = scheduled_marks(pairs, entries)
