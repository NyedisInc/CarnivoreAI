
from __future__ import annotations

import math
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple

import structlog

from src.core.safe_io.readonly_db import READONLY_TIMEOUT_QUICK_S, connect_readonly
from src.core.session_timeline.assemble import parse_time

logger = structlog.get_logger()

GRAINS: Tuple[int, ...] = (60, 300, 900, 3600, 14400, 86400)
MAX_CELLS = 600
MAX_ROWS = 20000
DEADLINE_SECONDS = 0.5
WALL_DEADLINE_SECONDS = 10.0
HOUR_ROW_SECONDS = 3600
MINUTE_ROW_SECONDS = 60
BUSY = "busy"
IDLE = "idle"


class Cell(NamedTuple):

    start: int
    span: int
    working: float
    observed: float


class BandUnreadable(Exception):
    pass


def grain_for(span_seconds: float) -> int:
    for grain in GRAINS:
        if span_seconds / grain <= MAX_CELLS:
            return grain
    return GRAINS[-1]


class Window(NamedTuple):

    conversation_id: str
    lo: int
    hi: int
    grain: int


def _query(count: int) -> str:
    from src.core.stats.plugin.schema import FLOOR_SQL  # noqa: PLC0415

    values = ",".join("(?,?,?,?,?)" for _ in range(count))
    return (f"WITH w(conversation_id, base, lo_minute, hi, grain) AS (VALUES {values}) "
            "SELECT a.conversation_id, w.base + ((a.minute_ts - w.base) / w.grain) * w.grain AS bucket, "
            f"MAX(CASE WHEN a.minute_ts < {FLOOR_SQL} THEN {HOUR_ROW_SECONDS} ELSE {MINUTE_ROW_SECONDS} END) "
            "AS row_span, MAX(w.grain) AS grain, SUM(a.working_seconds) AS working, "
            "SUM(a.observed_seconds) AS observed "
            "FROM activity_minutes a JOIN w ON a.conversation_id = w.conversation_id "
            f"WHERE a.minute_ts >= CASE WHEN a.minute_ts < {FLOOR_SQL} THEN w.base ELSE w.lo_minute END "
            "AND a.minute_ts < w.hi "
            "GROUP BY a.conversation_id, bucket ORDER BY a.conversation_id, bucket LIMIT ?")


def read_cells(stats_db: Path, windows: Sequence[Window]) -> Dict[str, List[Cell]]:
    windows = [w for w in windows if w.hi > w.lo]
    if not windows:
        return {}
    cpu_deadline, wall_deadline = time.thread_time() + DEADLINE_SECONDS, time.monotonic() + WALL_DEADLINE_SECONDS
    args: List[Any] = []
    for w in windows:
        args += [w.conversation_id, w.lo - w.lo % HOUR_ROW_SECONDS, w.lo - w.lo % MINUTE_ROW_SECONDS, w.hi, w.grain]
    args.append(MAX_ROWS + 1)
    with closing(connect_readonly(stats_db, timeout=READONLY_TIMEOUT_QUICK_S)) as conn:
        conn.set_progress_handler(
            lambda: 1 if time.thread_time() > cpu_deadline or time.monotonic() > wall_deadline else 0, 1000)
        try:
            rows = conn.execute(_query(len(windows)), args).fetchall()
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc):
                raise BandUnreadable("activity read over its time budget") from exc
            raise
    if len(rows) > MAX_ROWS:
        raise BandUnreadable("activity read over its row cap")
    by_conv = {w.conversation_id: w for w in windows}
    out: Dict[str, List[Cell]] = {}
    for conv, bucket, row_span, grain, working, observed in rows:
        w, row_span = by_conv[conv], int(row_span)
        first = max(int(bucket), w.lo - w.lo % row_span)
        last = min(int(bucket) + max(int(grain), row_span), -(-w.hi // row_span) * row_span)
        out.setdefault(conv, []).append(Cell(first, last - first, float(working or 0), float(observed or 0)))
    return out


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def runs(cells: Iterable[Cell], lo: float, hi: float) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    end_of_last: Optional[float] = None
    for cell in cells:
        state = BUSY if cell.working > 0 else IDLE if cell.observed > 0 else None
        a, b = max(lo, cell.start), min(hi, cell.start + cell.span)
        if state is None or b <= a:
            end_of_last = None
            continue
        worked = cell.working * (b - a) / cell.span if state == BUSY else 0.0
        last = out[-1] if out else None
        if last is not None and a <= last["_start"]:
            state = BUSY if BUSY in (state, last["state"]) else state
            last["state"], last["_end"] = state, max(last["_end"], b)
            last["busy_seconds"] += worked
        elif last is not None and last["state"] == state and end_of_last is not None and a <= end_of_last:
            last["_end"], last["busy_seconds"] = b, last["busy_seconds"] + worked
        else:
            out.append({"state": state, "_start": a, "_end": b, "busy_seconds": worked})
        end_of_last = b
    return [{"state": r["state"], "start": _iso(r["_start"]), "end": _iso(r["_end"]),
             "busy_seconds": round(r["busy_seconds"], 1)} for r in out]


def _span(bar: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    start, end = parse_time(bar.get("started_at")), parse_time(bar.get("ended_at"))
    if start is None or end is None or end <= start:
        return None
    return start.timestamp(), end.timestamp()


def attach(answer: Dict[str, Any], stats_db: Path) -> Dict[str, Any]:
    bars = answer.get("bars") or []
    for bar in bars:
        bar["activity"], bar["busy_seconds"] = None, None
    spans = {bar["conversation_id"]: s for bar in bars if (s := _span(bar)) is not None}
    if not spans:
        return answer
    if not stats_db.exists():
        logger.debug("session_timeline_activity_absent", path=str(stats_db))
        return answer
    windows = [Window(conv, math.floor(lo), math.ceil(hi), grain_for(hi - lo))
               for conv, (lo, hi) in sorted(spans.items())]
    try:
        cells = read_cells(stats_db, windows)
    except (BandUnreadable, sqlite3.Error) as exc:
        logger.warning("session_timeline_activity_unreadable", error=str(exc), conversations=len(spans))
        return answer
    for bar in bars:
        span = spans.get(bar["conversation_id"])
        found = runs(cells.get(bar["conversation_id"], []), *span) if span else []
        if found:
            bar["activity"] = found
            bar["busy_seconds"] = round(sum(r["busy_seconds"] for r in found), 1)
    return answer
