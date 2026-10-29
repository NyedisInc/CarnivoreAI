
from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import List, Optional

import structlog

from src.core.flow_data import main_db, mcp_events
from src.core.mcp_usage import old_names, store as usage_store

logger = structlog.get_logger()

RECOMPUTE_DAYS = 3
INCOMPLETE = "incomplete"
_RE_ENTRY = "NOT (caller_kind = 'pane' AND COALESCE(caller_session_id, '') LIKE 'mcp-token:%')"


def _day_start(day: date) -> float:
    return datetime.combine(day, dtime.min, tzinfo=timezone.utc).timestamp()


def collect(since_epoch: float) -> List[usage_store.Row]:
    with closing(main_db.open_main()) as conn:
        found = conn.execute(
            "SELECT strftime('%Y-%m-%d', started_at, 'unixepoch') AS day, tool, caller_kind, COALESCE(outcome, ?) AS outcome, "
            f"COUNT(DISTINCT call_id) AS calls FROM mcp_events WHERE started_at >= ? AND {_RE_ENTRY} "
            "GROUP BY day, tool, caller_kind, outcome", (INCOMPLETE, since_epoch)).fetchall()
    return [(r["day"], r["tool"], r["caller_kind"], r["outcome"], r["calls"]) for r in found]


def run(now: Optional[datetime] = None, store: Optional[usage_store.UsageStore] = None) -> int:
    store = store or usage_store.get_store()
    old_names.flush(store)
    today = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
    first = today - timedelta(days=RECOMPUTE_DAYS - 1)
    latest = store.latest_day()
    if latest is None:
        first_day, since = "0000-00-00", 0.0
    else:
        oldest_whole_day = today - timedelta(days=mcp_events.RETENTION_DAYS - 1)
        first = max(min(first, date.fromisoformat(latest)), oldest_whole_day)
        first_day, since = first.isoformat(), _day_start(first)
    written = store.replace_from(first_day, collect(since))
    store.prune(today)
    return written
