
from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import structlog

logger = structlog.get_logger()

MIN_DAYS, MAX_DAYS, DEFAULT_DAYS = 1, 90, 30
DEADLINE_SECONDS = 1.0
OK, NO_STATS, NO_SESSIONS, UNREADABLE = "ok", "no_stats", "no_sessions", "unreadable"


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def conversation_sessions(conn: sqlite3.Connection) -> Dict[str, Set[str]]:
    from src.core.lineage import constants as K  # noqa: PLC0415
    from src.core.lineage import graph  # noqa: PLC0415
    from src.core.session_conversations import view  # noqa: PLC0415

    out: Dict[str, Set[str]] = {}
    pairs: List[Any] = [(r["claude_session_uuid"], r["session_uuid"]) for r in conn.execute(
        "SELECT session_uuid, claude_session_uuid FROM sessions WHERE claude_session_uuid IS NOT NULL")]
    if view.index_ready(conn):
        pairs += [(r["conversation_id"], r["session_uuid"]) for r in conn.execute(
            "SELECT conversation_id, session_uuid FROM conversation_index WHERE session_uuid IS NOT NULL")]
    if graph.ready(conn):
        marks = ",".join("?" for _ in K.CONTINUATION_KINDS)
        pairs += [(r["parent_id"], r["child_id"]) for r in conn.execute(
            f"SELECT parent_id, child_id FROM {K.EDGES_TABLE} WHERE child_type = ? AND parent_type = ? "
            f"AND edge_kind IN ({marks})", (K.NODE_SESSION, K.NODE_CONVERSATION, *K.CONTINUATION_KINDS))]
    for conversation, session in pairs:
        out.setdefault(conversation, set()).add(session)
    return out


def _read_activity(stats_db: Path, lo: int, hi: int) -> Dict[str, Any]:
    deadline = time.monotonic() + DEADLINE_SECONDS
    with closing(sqlite3.connect(stats_db.as_uri() + "?mode=ro", uri=True, timeout=1)) as conn:
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
        try:
            rows = conn.execute(
                "SELECT conversation_id, strftime('%Y-%m-%d', minute_ts, 'unixepoch', 'localtime') AS day, "
                "SUM(working_seconds), MAX(CASE WHEN working_seconds > 0 THEN minute_ts END) "
                "FROM activity_minutes WHERE minute_ts >= ? AND minute_ts < ? GROUP BY conversation_id, day",
                (lo, hi)).fetchall()
            since = conn.execute("SELECT MIN(minute_ts) FROM activity_minutes").fetchone()[0]
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc):
                raise TimeoutError("session usage read over its time budget") from exc
            raise
    return {"rows": rows, "since": since}


def _fold(rows: List[Any], owners: Dict[str, Set[str]]) -> Dict[str, Dict[str, Any]]:
    seconds: Dict[str, float] = {}
    days: Dict[str, Set[str]] = {}
    last: Dict[str, Optional[int]] = {}
    for conversation, day, working, last_ts in rows:
        for session in owners.get(conversation, ()):
            seconds[session] = seconds.get(session, 0.0) + float(working or 0)
            if working and working > 0:
                days.setdefault(session, set()).add(day)
            if last_ts is not None:
                last[session] = max(last_ts, last.get(session) or 0)
            else:
                last.setdefault(session, None)
    return {s: {"worked_s": round(seconds[s], 1), "active_days": len(days.get(s, ())),
                "last_worked_at": _iso(last[s]) if last.get(s) else None} for s in seconds}


def build(days: int = DEFAULT_DAYS, *, now: Optional[datetime] = None, db: Optional[Path] = None,
          stats_db: Optional[Path] = None) -> Dict[str, Any]:
    from src.core.db import DatastoreUnreadableError, connect  # noqa: PLC0415
    from src.core.pipeline import plugin_db  # noqa: PLC0415
    from src.core.stats.plugin.pipeline_plugin import STATS  # noqa: PLC0415

    days = max(MIN_DAYS, min(MAX_DAYS, int(days)))
    hi = int((now or datetime.now(timezone.utc)).timestamp())
    answer: Dict[str, Any] = {"state": OK, "days": days, "measured_since": None, "by_session": {}}
    if db is None:
        from src.config import settings  # noqa: PLC0415
        from src.core.db import db_path_for  # noqa: PLC0415

        db = db_path_for(settings.get_state_dir())
    stats_db = stats_db or plugin_db.db_path(db.parent, STATS)
    if not stats_db.exists():
        return {**answer, "state": NO_STATS}
    try:
        with closing(connect(db, create=False)) as conn:
            owners = conversation_sessions(conn)
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.warning("session_usage_datastore_unreadable", error=str(exc))
        return {**answer, "state": NO_SESSIONS}
    try:
        read = _read_activity(stats_db, hi - days * 86400, hi)
    except TimeoutError as exc:
        logger.warning("session_usage_stats_slow", error=str(exc))
        return {**answer, "state": UNREADABLE}
    except sqlite3.Error as exc:
        logger.warning("session_usage_stats_unreadable", error=str(exc))
        return {**answer, "state": NO_STATS}
    answer["measured_since"] = _iso(read["since"]) if read["since"] is not None else None
    answer["by_session"] = _fold(read["rows"], owners)
    return answer
