
from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Tuple

import structlog

from src.core.automations import pause, plugin_schedules, timer_status, wake_schedule
from src.api.automation_timers_listing import is_local, scheduled_marks
from src.core.db import DatastoreUnreadableError
from src.models.records import SessionRecord

logger = structlog.get_logger()


def _read_automations(store: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    return ([], {}) if pause.is_paused() else (store.list_all(), store.latest_stopped_runs())


def _clear(record: SessionRecord) -> None:
    record.next_wake_at = record.automations_state = record.automations_total = record.automations_enabled = record.automations_next = None


Stamp = Tuple[Optional[float], Optional[str], Optional[int], Optional[int], Optional[List[Any]]]


async def _stamps(app_state: Any, asleep: List[SessionRecord], infos: Optional[List[Any]]) -> Dict[str, Stamp]:
    wanted = [{"session_uuid": r.session_uuid, "project_id": r.project_id} for r in asleep]
    uuids = [w["session_uuid"] for w in wanted]
    automations: Optional[Dict[str, List[Any]]] = None
    runs: Dict[str, Dict[str, Any]] = {}
    store = getattr(app_state, "automation_store", None)
    if store is not None:
        try:
            rows, runs = await asyncio.to_thread(_read_automations, store)
            automations = wake_schedule.waking_by_session(rows, uuids)
        except (OSError, sqlite3.Error, DatastoreUnreadableError) as exc:
            logger.warning("listing.asleep_wake.automations_unreadable", error=type(exc).__name__)
    entries: Optional[Dict[str, List[Dict[str, Any]]]] = None
    try:
        entries = await plugin_schedules.wake_entries(wanted, None if infos is None else [i for i in infos if is_local(i)], app_state)
    except plugin_schedules.PluginSchedulesUnreadable:
        pass
    out: Dict[str, Stamp] = {}
    for uuid in uuids:
        pairs = [(a, runs.get(a["automation_id"])) for a in (automations or {}).get(uuid, [])]
        found = (entries or {}).get(uuid, [])
        due = [t for t in [wake_schedule.next_due(a) for a, _ in pairs] + [e.get("next_fire_at") for e in found] if t]
        next_wake = min(due) if due else None
        if automations is None or entries is None:
            out[uuid] = (next_wake, None, None, None, None)
            continue
        status = timer_status.roll_up(pairs + [timer_status.pair_of_schedule(e) for e in found])
        out[uuid] = (next_wake, status.state, status.total, status.enabled, scheduled_marks(pairs, found))
    return out


async def stamp_next_wake(app_state: Any, records: Iterable[SessionRecord], infos: Optional[List[Any]] = None,
                          shared: Optional[Dict[str, Any]] = None) -> None:
    asleep = [r for r in records if r.asleep and not r.archived_at]
    for record in asleep:
        _clear(record)
    if not asleep:
        return
    key = tuple((r.session_uuid, r.project_id) for r in asleep)
    if shared is not None and shared.get("key") == key:
        stamps = shared["stamps"]
    else:
        stamps = await _stamps(app_state, asleep, infos)
        if shared is not None:
            shared.update(key=key, stamps=stamps)
    for record in asleep:
        next_wake, state, total, enabled, marks = stamps[record.session_uuid]
        record.next_wake_at, record.automations_state, record.automations_total, record.automations_enabled = next_wake, state, total, enabled
        record.automations_next = list(marks) if marks is not None else None
