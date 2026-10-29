
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from src.core.timers.contract import (
    TOOL_CRON_CREATE,
    TOOL_CRON_DELETE,
    TOOL_WAKEUP,
    check_call,
    check_result,
)
from src.core.timers.cron import next_fire_text
from src.core.timers.index import SleepCall, TimerCall, TimerIndex
from src.core.timers.redact import summary
from src.models.timers import TimerCounts, TimerInfo

FIRE_SLACK = timedelta(seconds=1)

MAX_ROWS: int = 50

PROCESS_ALIVE = "alive"
PROCESS_GONE = "gone"
PROCESS_UNKNOWN = "unknown"

_EXPIRY_RE = re.compile(r"Auto-expires after (\d+) days?")


@dataclass(frozen=True)
class ProcessFact:

    state: str
    started_at: Optional[datetime] = None


UNKNOWN_PROCESS = ProcessFact(PROCESS_UNKNOWN)


def iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class _Row:

    call: TimerCall
    kind: str
    status: Optional[str] = None
    ident: str = ""
    fire_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    recurring: Optional[bool] = None
    durable: Optional[bool] = None


def _inputs(call: TimerCall) -> Dict:
    return call.input if isinstance(call.input, dict) else {}


def _result(call: TimerCall) -> Dict:
    return call.result if isinstance(call.result, dict) else {}


def _shape_or_refusal(call: TimerCall) -> Optional[str]:
    if not check_call(call.tool, call.input).recognized:
        return "shape_unrecognized"
    if isinstance(call.result, str):
        return "refused"
    if isinstance(call.result, dict) and not check_result(call.tool, call.result).recognized:
        return "shape_unrecognized"
    return None


def _wakeup_fire(call: TimerCall) -> datetime:
    scheduled = _result(call).get("scheduledFor")
    if isinstance(scheduled, int) and not isinstance(scheduled, bool):
        return datetime.fromtimestamp(scheduled / 1000, tz=timezone.utc)
    return call.created_at + timedelta(seconds=int(_inputs(call).get("delaySeconds", 0)))


def _fired(index: TimerIndex, fire_at: Optional[datetime]) -> bool:
    return (fire_at is not None and index.last_turn_start is not None
            and index.last_turn_start >= fire_at - FIRE_SLACK)


def _wakeups(index: TimerIndex) -> List[_Row]:
    rows = [_Row(call, "wakeup", ident=call.tool_use_id)
            for call in index.calls if call.tool == TOOL_WAKEUP]
    newest_valid = None
    for position in range(len(rows) - 1, -1, -1):
        row = rows[position]
        row.status = row.status or _shape_or_refusal(row.call)
        if row.status is not None:
            continue
        row.fire_at = _wakeup_fire(row.call)
        if _inputs(row.call).get("stop") is True:
            row.status = "cancelled"
            for earlier in rows[:position]:
                earlier.status = earlier.status or "cancelled"
            newest_valid = newest_valid or row
            continue
        if newest_valid is not None:
            row.status = "superseded"
        elif _fired(index, row.fire_at):
            row.status = "fired"
        newest_valid = newest_valid or row
    return rows


def _crons(index: TimerIndex, now: datetime) -> List[_Row]:
    deleted: Dict[str, datetime] = {}
    for call in index.calls:
        if call.tool == TOOL_CRON_DELETE and _shape_or_refusal(call) is None:
            job = _inputs(call).get("id")
            if isinstance(job, str):
                deleted[job] = call.created_at
    rows: List[_Row] = []
    for call in index.calls:
        if call.tool != TOOL_CRON_CREATE:
            continue
        row = _Row(call, "cron", ident=call.tool_use_id)
        rows.append(row)
        row.status = _shape_or_refusal(call)
        if row.status is not None:
            continue
        result, inputs = _result(call), _inputs(call)
        job = result.get("id")
        if isinstance(job, str) and job:
            row.ident = job
        recurring = result.get("recurring", inputs.get("recurring"))
        row.recurring = recurring if isinstance(recurring, bool) else None
        durable = result.get("durable", inputs.get("durable"))
        row.durable = durable if isinstance(durable, bool) else None
        match = _EXPIRY_RE.search(call.result_text or "")
        if match:
            row.expires_at = call.created_at + timedelta(days=int(match.group(1)))
        if row.ident in deleted and deleted[row.ident] >= call.created_at:
            row.status = "cancelled"
            continue
        if row.recurring is False:
            row.fire_at = next_fire_text(inputs["cron"], call.created_at)
            if _fired(index, row.fire_at):
                row.status = "fired"
            continue
        if row.expires_at is not None and now >= row.expires_at:
            row.status = "expired"
            continue
        upcoming = next_fire_text(inputs["cron"], now)
        if upcoming is not None and row.expires_at is not None and upcoming >= row.expires_at:
            upcoming = None
        row.fire_at = upcoming
    return rows


def _sleep_row(sleep_call: SleepCall, now: datetime) -> _Row:
    fire_at = sleep_call.created_at + timedelta(seconds=sleep_call.delay_seconds)
    call = TimerCall(
        "Bash:sleep", sleep_call.tool_use_id, sleep_call.created_at,
        {"delaySeconds": sleep_call.delay_seconds, "prompt": sleep_call.command},
    )
    row = _Row(call, "sleep", ident=sleep_call.tool_use_id, fire_at=fire_at)
    if now >= fire_at:
        row.status = "fired"
    return row


def _sleeps(index: TimerIndex, now: datetime) -> List[_Row]:
    return [_sleep_row(sleep_call, now) for sleep_call in index.sleeps]


def _apply_liveness(rows: List[_Row], process: ProcessFact) -> None:
    for row in rows:
        if row.status is not None:
            continue
        if process.state == PROCESS_UNKNOWN:
            row.status = "unknown"
        elif process.state == PROCESS_GONE:
            row.status = "lost"
        elif process.started_at is not None and process.started_at > row.call.created_at:
            row.status = "lost"
        else:
            row.status = "live"


def _info(row: _Row) -> TimerInfo:
    inputs = _inputs(row.call)
    result = _result(row.call)
    delay = inputs.get("delaySeconds")
    human = result.get("humanSchedule")
    return TimerInfo(
        id=row.ident, kind=row.kind, status=row.status or "unknown",
        cron=summary(inputs.get("cron"), 80),
        human_schedule=summary(human, 80) if row.kind == "cron" else None,
        delay_seconds=delay if isinstance(delay, int) and not isinstance(delay, bool) else None,
        recurring=row.recurring, durable=row.durable,
        created_at=iso(row.call.created_at) or "",
        fire_at=iso(row.fire_at), expires_at=iso(row.expires_at),
        prompt=summary(inputs.get("prompt")), reason=summary(inputs.get("reason")),
    )


def derive_timers(
    index: TimerIndex, process: ProcessFact, now: datetime
) -> Tuple[List[TimerInfo], TimerCounts, Optional[datetime]]:
    rows = _wakeups(index) + _crons(index, now) + _sleeps(index, now)
    _apply_liveness(rows, process)
    tally: Dict[str, int] = {}
    for row in rows:
        tally[row.status or "unknown"] = tally.get(row.status or "unknown", 0) + 1
    counts = TimerCounts(
        total=len(rows),
        **{name: tally.get(name, 0) for name in (
            "live", "fired", "cancelled", "superseded", "expired", "lost",
            "refused", "unknown", "shape_unrecognized")},
    )
    upcoming = [row.fire_at for row in rows if row.status == "live" and row.fire_at is not None]
    ordered = sorted(rows, key=lambda row: row.call.created_at, reverse=True)
    return [_info(row) for row in ordered[:MAX_ROWS]], counts, min(upcoming, default=None)


__all__ = [
    "ProcessFact", "UNKNOWN_PROCESS", "PROCESS_ALIVE", "PROCESS_GONE",
    "PROCESS_UNKNOWN", "derive_timers", "iso", "MAX_ROWS",
]
