
from __future__ import annotations

import math
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import structlog

from src.cplugs.huddle import recurrence, rules
from src.cplugs.huddle.rules import TaskManagerInvalid

logger = structlog.get_logger()


AT = "at"
KINDS = (AT,)
FIELD = "start_trigger"
MAX_ERROR = 300

SELECT_COLS = (
    "(SELECT t.kind FROM work_item_triggers t WHERE t.item_id = work_items.id) AS trigger_kind, "
    "(SELECT t.fire_at FROM work_item_triggers t WHERE t.item_id = work_items.id) AS trigger_fire_at, "
    "(SELECT t.fired_at FROM work_item_triggers t WHERE t.item_id = work_items.id) AS trigger_fired_at, "
    "(SELECT t.last_error FROM work_item_triggers t WHERE t.item_id = work_items.id) AS trigger_error, "
    "(SELECT t.repeat_rule FROM work_item_triggers t WHERE t.item_id = work_items.id) AS trigger_repeat, "
    "(SELECT t.paused FROM work_item_triggers t WHERE t.item_id = work_items.id) AS trigger_paused, "
    "(SELECT t.last_fired_at FROM work_item_triggers t WHERE t.item_id = work_items.id) AS trigger_last_fired"
)

JOINED_COLS = ("t.kind AS trigger_kind, t.fire_at AS trigger_fire_at, t.fired_at AS trigger_fired_at, t.last_error AS trigger_error, "
               "t.repeat_rule AS trigger_repeat, t.paused AS trigger_paused, t.last_fired_at AS trigger_last_fired")

_listeners: List[Callable[[], None]] = []
_write_listeners: List[Callable[[], None]] = []


def subscribe(listener: Callable[[], None]) -> Callable[[], None]:
    _listeners.append(listener)
    return lambda: _listeners.remove(listener) if listener in _listeners else None


def subscribe_writes(listener: Callable[[], None]) -> Callable[[], None]:
    _write_listeners.append(listener)
    return lambda: _write_listeners.remove(listener) if listener in _write_listeners else None


def wrote() -> None:
    if getattr(_local, "rearmed", False):
        _local.rearmed = False
        nudge()
    for listener in list(_write_listeners):
        listener()


def nudge() -> None:
    for listener in list(_listeners):
        listener()


def parse_fire_at(value: object, now: float) -> Optional[float]:
    if not isinstance(value, str):
        raise TaskManagerInvalid("fire_at must be an ISO 8601 time with a UTC offset, or an empty string to cancel")
    text = value.strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise TaskManagerInvalid("fire_at must be an ISO 8601 time with a UTC offset, e.g. 2026-10-06T15:00:00-04:00") from exc
    if moment.tzinfo is None:
        raise TaskManagerInvalid("fire_at needs a UTC offset (e.g. -04:00 or Z), so the moment is the same on every machine")
    stamp = float(math.ceil(moment.timestamp()))
    if stamp <= now:
        raise TaskManagerInvalid("fire_at must be in the future")
    return stamp


def cancel(conn: sqlite3.Connection, item_id: int) -> bool:
    return conn.execute("DELETE FROM work_item_triggers WHERE item_id = ?", (item_id,)).rowcount > 0


def current_fire_at(conn: sqlite3.Connection, item_id: int) -> Optional[float]:
    row = conn.execute("SELECT fire_at FROM work_item_triggers WHERE item_id = ? AND fired_at IS NULL", (item_id,)).fetchone()
    return None if row is None else row[0]


def next_due(conn: sqlite3.Connection) -> Optional[float]:
    row = conn.execute("SELECT MIN(t.fire_at) FROM work_item_triggers t JOIN work_items i ON i.id = t.item_id "
                       "WHERE t.fired_at IS NULL AND t.paused = 0 AND t.kind = ? AND i.deleted = 0", (AT,)).fetchone()
    return row[0] if row else None


def due_ids(conn: sqlite3.Connection, now: float) -> List[int]:
    return [r[0] for r in conn.execute(
        "SELECT t.item_id FROM work_item_triggers t JOIN work_items i ON i.id = t.item_id "
        "WHERE t.fired_at IS NULL AND t.paused = 0 AND t.kind = ? AND t.fire_at <= ? AND i.deleted = 0 ORDER BY t.fire_at, t.item_id",
        (AT, now))]


def rule_of(text: Optional[str], item_id: object = None) -> Optional[Dict[str, Any]]:
    try:
        return recurrence.loads(text)
    except ValueError as exc:
        logger.error("task_manager_repeat_rule_corrupt", item=item_id, error=str(exc)[:100])
        return None


def claim(conn: sqlite3.Connection, item_id: int, now: float, *, deliver: bool = True) -> bool:
    row = conn.execute("SELECT fire_at, repeat_rule FROM work_item_triggers WHERE item_id = ? AND fired_at IS NULL AND kind = ? "
                       "AND paused = 0 AND fire_at <= ?", (item_id, AT, now)).fetchone()
    if row is None:
        return False
    rule = rule_of(row["repeat_rule"], item_id)
    if rule is None:
        return conn.execute("UPDATE work_item_triggers SET fired_at = ?, last_error = NULL, updated_at = ? "
                            "WHERE item_id = ? AND fired_at IS NULL AND kind = ? AND fire_at <= ?",
                            (now, now, item_id, AT, now)).rowcount == 1
    following = recurrence.next_after(rule, now, anchor=row["fire_at"])
    return conn.execute("UPDATE work_item_triggers SET fire_at = ?, last_fired_at = CASE WHEN ? THEN ? ELSE last_fired_at END, "
                        "last_error = NULL, updated_at = ? WHERE item_id = ? AND fired_at IS NULL AND paused = 0 AND fire_at = ?",
                        (following, int(deliver), now, now, item_id, row["fire_at"])).rowcount == 1


def claim_now(conn: sqlite3.Connection, item_id: int, now: float) -> None:
    row = conn.execute("SELECT fire_at, repeat_rule FROM work_item_triggers WHERE item_id = ? AND kind = ?", (item_id, AT)).fetchone()
    if row is None:
        return
    rule = rule_of(row["repeat_rule"], item_id)
    if rule is None:
        conn.execute("UPDATE work_item_triggers SET fired_at = ?, last_error = NULL, updated_at = ? WHERE item_id = ?", (now, now, item_id))
        return
    following = recurrence.next_after(rule, now, anchor=row["fire_at"]) if row["fire_at"] <= now else row["fire_at"]
    conn.execute("UPDATE work_item_triggers SET fire_at = ?, fired_at = NULL, last_fired_at = ?, last_error = NULL, updated_at = ? WHERE item_id = ?",
                 (following, now, now, item_id))


SKIP_PARKED = "not sent: the item is on the back burner"
SKIP_JOE = "not sent: the item is waiting on you"
SKIP_WAITING = "not sent: the item is waiting"


SKIP_REASONS = (SKIP_PARKED, SKIP_JOE, SKIP_WAITING)

_local = threading.local()


def resume_skipped(conn: sqlite3.Connection, item_id: int, now: float, reasons: Sequence[str]) -> bool:
    marks = ", ".join("?" for _ in reasons)
    armed = conn.execute(f"UPDATE work_item_triggers SET fire_at = ?, fired_at = NULL, last_error = NULL, updated_at = ? "
                         f"WHERE item_id = ? AND repeat_rule IS NULL AND last_error IN ({marks})", (now, now, item_id, *reasons)).rowcount > 0
    if armed:
        _local.rearmed = True
    return armed


def resume_on_move(conn: sqlite3.Connection, row: Mapping[str, Any], new_state: str, now: float) -> bool:
    old = row["state"]
    if new_state == old or new_state == rules.TODO or new_state in rules.APPROVED_STATES:
        return False
    reasons = [SKIP_JOE]
    if old == rules.TODO:
        reasons.append(SKIP_PARKED)
    if new_state != rules.WAITING:
        reasons.append(SKIP_WAITING)
    return resume_skipped(conn, row["id"], now, reasons)


def record_error(conn: sqlite3.Connection, item_id: int, message: str, now: float) -> None:
    conn.execute("UPDATE work_item_triggers SET last_error = ?, updated_at = ? WHERE item_id = ?",
                 (message[:MAX_ERROR], now, item_id))


def wire(row: sqlite3.Row) -> Optional[Dict[str, object]]:
    if row["trigger_kind"] is None:
        return None
    stamp = row["trigger_fire_at"]
    return {"kind": row["trigger_kind"], "fire_at": stamp,
            "fire_at_iso": None if stamp is None else datetime.fromtimestamp(stamp).astimezone().isoformat(timespec="seconds"),
            "fired_at": row["trigger_fired_at"], "last_error": row["trigger_error"],
            "repeat": rule_of(row["trigger_repeat"], row["id"]), "paused": bool(row["trigger_paused"]),
            "last_fired_at": row["trigger_last_fired"]}


def is_pending(row: sqlite3.Row) -> bool:
    if "trigger_kind" not in row.keys():
        return False
    if row["trigger_kind"] != AT or row["trigger_fire_at"] is None or row["trigger_fired_at"] is not None:
        return False
    if "trigger_repeat" in row.keys() and row["trigger_repeat"]:
        return not row["trigger_paused"]
    return not row["trigger_error"]


def refuses(state: str) -> Optional[str]:
    if state in rules.APPROVED_STATES:
        return "an approved item is done; it cannot be scheduled"
    return None


UNSET: Any = object()


@dataclass(frozen=True)
class Plan:

    cancel: bool = False
    fire_at: Optional[float] = None
    repeat: Any = UNSET
    paused: Optional[bool] = None


def plan(conn: sqlite3.Connection, item_id: int, new_state: str, fire_at: Optional[str], repeat: object,
         paused: Optional[bool], now: float) -> Optional[Plan]:
    row = conn.execute("SELECT fire_at, fired_at, repeat_rule, paused FROM work_item_triggers WHERE item_id = ?", (item_id,)).fetchone()
    asking = (fire_at not in (None, "")) or (repeat not in (None, "")) or paused is not None
    why = refuses(new_state)
    if why:
        if asking:
            raise TaskManagerInvalid(why)
        return Plan(cancel=True) if row else None
    if fire_at == "":
        return Plan(cancel=True) if row else None
    if fire_at is None and repeat is None and paused is None:
        return None
    stamp = parse_fire_at(fire_at, now) if fire_at is not None else None
    old_rule = rule_of(row["repeat_rule"], item_id) if row else None
    rule = recurrence.parse_rule(repeat) if repeat is not None else old_rule
    if repeat is not None and rule is None and stamp is None and not row:
        return None
    was_paused = bool(row["paused"]) if row else False
    if paused is not None and rule is None:
        raise TaskManagerInvalid("only a repeating schedule can be paused; cancel the schedule instead")
    if stamp is None and repeat is not None and rule is not None and (rule != old_rule or not row or row["fired_at"] is not None):
        pending_future = bool(row) and row["fired_at"] is None and row["fire_at"] > now
        stamp = row["fire_at"] if pending_future else recurrence.next_after(rule, now)
    if stamp is None and paused is False and was_paused and rule is not None and row["fire_at"] <= now:
        stamp = recurrence.next_after(rule, now, anchor=row["fire_at"])
    new_paused = was_paused if paused is None else paused
    if repeat is not None and rule is None:
        new_paused = False
    if row and row["fired_at"] is None and stamp in (None, row["fire_at"]) and rule == old_rule and new_paused == was_paused:
        return None
    if stamp is None and not row:
        return None
    return Plan(fire_at=stamp, repeat=rule if repeat is not None else UNSET, paused=new_paused)


def apply(conn: sqlite3.Connection, item_id: int, change: Plan, now: float) -> None:
    if change.cancel:
        cancel(conn, item_id)
        return
    row = conn.execute("SELECT fire_at, repeat_rule, paused FROM work_item_triggers WHERE item_id = ?", (item_id,)).fetchone()
    fire_at = change.fire_at if change.fire_at is not None else (row["fire_at"] if row else None)
    rule_text = (row["repeat_rule"] if row else None) if change.repeat is UNSET else recurrence.dumps(change.repeat)
    paused = int(change.paused) if change.paused is not None else (row["paused"] if row else 0)
    rearm = change.fire_at is not None
    conn.execute(
        "INSERT INTO work_item_triggers (item_id, kind, fire_at, fired_at, last_error, updated_at, repeat_rule, paused) "
        "VALUES (?, ?, ?, NULL, NULL, ?, ?, ?) ON CONFLICT(item_id) DO UPDATE SET kind = excluded.kind, "
        "fire_at = excluded.fire_at, fired_at = CASE WHEN ? THEN NULL ELSE fired_at END, "
        "last_error = CASE WHEN ? THEN NULL ELSE last_error END, updated_at = excluded.updated_at, "
        "repeat_rule = excluded.repeat_rule, paused = excluded.paused",
        (item_id, AT, fire_at, now, rule_text, paused, int(rearm), int(rearm)))
