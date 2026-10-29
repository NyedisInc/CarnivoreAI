from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Iterable

from .catalog import METRICS

USAGE_METRICS: frozenset[str] = frozenset(k for k, (_, table) in METRICS.items()
                                          if table in ("minute_usage", "minute_counters"))


CLOCK_METRICS: frozenset[str] = frozenset(("observed_seconds", "running_seconds",
                                           "average_working_agents", "average_running_agents"))
CHART_MIN_S: float = 60.0
NOTICE_MIN_S: float = 15.0
COVERAGE_STEP_S: int = 300
SIDE_READS: tuple[str, ...] = ("dimensions", "coverage", "tripwires")


@dataclass
class PassChanges:

    metrics: set[str] = field(default_factory=set)
    live: bool = False
    events: bool = False
    dimensions: bool = False
    coverage: bool = False
    tripwires: bool = False

    @property
    def empty(self) -> bool:
        return not (self.metrics or self.live or self.events or self.dimensions or self.coverage
                    or self.tripwires)

    @property
    def clock_only(self) -> bool:
        return bool(self.metrics) and self.metrics <= CLOCK_METRICS and not (
            self.live or self.events or self.dimensions or self.coverage or self.tripwires)

    @property
    def has_live_part(self) -> bool:
        return bool(self.live or self.events or self.dimensions or self.coverage or self.tripwires)

    def due(self, since_last: float, since_chart: float | None = None) -> bool:
        if self.empty:
            return False
        if self.has_live_part and since_last >= NOTICE_MIN_S:
            return True
        since_chart = since_last if since_chart is None else since_chart
        return bool(self.metrics) and since_last >= NOTICE_MIN_S and since_chart >= CHART_MIN_S

    def for_frame(self, since_chart: float) -> "PassChanges":
        send_metrics = since_chart >= CHART_MIN_S
        return PassChanges(metrics=set(self.metrics) if send_metrics else set(), live=self.live,
                           events=self.events, dimensions=self.dimensions, coverage=self.coverage,
                           tripwires=self.tripwires)

    def frame_field(self) -> dict[str, Any]:
        return {"metrics": sorted(self.metrics), "live": self.live, "events": self.events,
                "dimensions": self.dimensions, "coverage": self.coverage, "tripwires": self.tripwires,
                "clock_only": self.clock_only}


def summarise(*, published_sources: int, activity_metrics: Iterable[str], live_before: dict | None,
              live_after: dict | None, events_before: int, events_after: int,
              sides_before: dict | None = None, sides_after: dict | None = None) -> PassChanges:
    changes = PassChanges(metrics=set(activity_metrics))
    if published_sources > 0:
        changes.metrics |= USAGE_METRICS
    if sides_after is None:
        moved = published_sources > 0 or "starts" in changes.metrics
        changes.dimensions = changes.coverage = changes.tripwires = moved
    else:
        before = sides_before or {}
        changes.dimensions = before.get("dimensions") != sides_after.get("dimensions")
        changes.coverage = before.get("coverage") != sides_after.get("coverage")
        changes.tripwires = before.get("tripwires") != sides_after.get("tripwires")
    changes.live = (live_before or {}) != (live_after or {})
    changes.events = events_after != events_before
    return changes


_SIDE_SQL: dict[str, tuple[str, ...]] = {
    "dimensions": (
        "SELECT COUNT(*) FROM dim_model", "SELECT COUNT(*) FROM dim_project",
        "SELECT COUNT(DISTINCT provider || '|' || agent_kind || '|' || COALESCE(account_id, '')) FROM dim_source",
        "SELECT COUNT(DISTINCT account_id || '|' || window) FROM quota_hour"),
    "coverage": (
        "SELECT state, COUNT(*) FROM stats_backfill GROUP BY state ORDER BY state",
        "SELECT COUNT(*) FROM plugin_cursors",
        "SELECT COUNT(*), MAX(start_ts), MAX(COALESCE(end_ts, 0)) FROM stats_disabled_spans",
        f"SELECT MAX(t) / {COVERAGE_STEP_S} FROM usage_minute"),
    "tripwires": ("SELECT * FROM stats_tripwires ORDER BY id",),
}


def side_fingerprints(store: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    with store.connect(readonly=True) as conn:
        for side, statements in _SIDE_SQL.items():
            digest = hashlib.sha256()
            for sql in statements:
                try:
                    rows = conn.execute(sql).fetchall()
                except sqlite3.OperationalError as exc:
                    rows = [("missing", str(exc))]
                digest.update(repr([tuple(row) for row in rows]).encode())
            out[side] = digest.hexdigest()[:16]
    return out


def last_event_id(store: Any) -> int:
    with store.connect(readonly=True) as conn:
        row = conn.execute("SELECT MAX(id) FROM stats_events").fetchone()
    return int(row[0] or 0)
