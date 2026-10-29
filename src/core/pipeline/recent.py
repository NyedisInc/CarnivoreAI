
from __future__ import annotations

import sqlite3
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import structlog

logger = structlog.get_logger()

ROW_LIMIT: int = 100
NAME_TTL_SECONDS: float = 60.0
NEGATIVE_TTL_SECONDS: float = 5.0
NAME_CACHE_LIMIT: int = 4096
NAME_QUERY_BATCH: int = 500

SCOPE_SESSION: str = "session"
SCOPE_PROJECT: str = "project"
SCOPE_MACHINE: str = "machine"

KIND_DELIVERY: str = "delivery"
KIND_REBUILD: str = "rebuild"

OUTCOME_OK: str = "ok"
OUTCOME_FAILED: str = "failed"
OUTCOME_PARKED: str = "parked"
OUTCOMES: Tuple[str, ...] = (OUTCOME_OK, OUTCOME_FAILED, OUTCOME_PARKED)

ERROR_CLASS_CHARS: int = 60


@dataclass(frozen=True)
class Area:

    session_uuid: Optional[str] = None
    session: Optional[str] = None
    project_id: Optional[int] = None
    project: Optional[str] = None

    @property
    def scope(self) -> str:
        if self.session_uuid:
            return SCOPE_SESSION
        if self.project_id is not None:
            return SCOPE_PROJECT
        return SCOPE_MACHINE

    @property
    def key(self) -> str:
        if self.session_uuid:
            return f"{SCOPE_SESSION}:{self.session_uuid}"
        if self.project_id is not None:
            return f"{SCOPE_PROJECT}:{self.project_id}"
        return SCOPE_MACHINE


MACHINE: Area = Area()

Resolver = Callable[[Sequence[str]], Mapping[str, Area]]


def no_names(conversation_ids: Sequence[str]) -> Mapping[str, Area]:
    return {}


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def _fill(found: Dict[str, Dict[str, Any]], conv: str, **values: Any) -> None:
    row = found.setdefault(conv, {"session_uuid": None, "session": None, "project_id": None, "project": None})
    for key, value in values.items():
        if row.get(key) in (None, "") and value not in (None, ""):
            row[key] = value


def read_names(conn: sqlite3.Connection, conversation_ids: Sequence[str]) -> Dict[str, Area]:
    ids = [c for c in dict.fromkeys(conversation_ids) if c]
    found: Dict[str, Dict[str, Any]] = {}
    for start in range(0, len(ids), NAME_QUERY_BATCH):
        chunk = ids[start:start + NAME_QUERY_BATCH]
        marks = ", ".join("?" for _ in chunk)
        if _has_table(conn, "conversation_index"):
            for conv, uuid, sname, pid, pname in conn.execute(
                    "SELECT conversation_id, session_uuid, session_name, project_id, project_name "
                    f"FROM conversation_index WHERE conversation_id IN ({marks})", chunk):
                _fill(found, conv, session_uuid=uuid, session=sname, project_id=pid, project=pname)
        if _has_table(conn, "sessions"):
            for conv, uuid, pid, name in conn.execute(
                    "SELECT claude_session_uuid, session_uuid, project_id, COALESCE(NULLIF(title, ''), "
                    f"NULLIF(claude_title, ''), tmux_name) FROM sessions WHERE claude_session_uuid IN ({marks}) "
                    "ORDER BY id DESC", chunk):
                _fill(found, conv, session_uuid=uuid, project_id=pid, session=name)
    missing = sorted({r["project_id"] for r in found.values() if r["project_id"] is not None and not r["project"]})
    if missing and _has_table(conn, "projects"):
        names = dict(conn.execute(f"SELECT id, display_name FROM projects WHERE id IN "
                                  f"({', '.join('?' for _ in missing)})", missing).fetchall())
        for row in found.values():
            if row["project_id"] in names and not row["project"]:
                row["project"] = names[row["project_id"]]
    return {conv: Area(row["session_uuid"], row["session"], row["project_id"], row["project"])
            for conv, row in found.items()}


def db_resolver(db_path: Optional[Path]) -> Resolver:
    if db_path is None:
        return no_names

    def resolve(conversation_ids: Sequence[str]) -> Mapping[str, Area]:
        from src.core.db import DatastoreUnreadableError, connect

        if not conversation_ids:
            return {}
        try:
            conn = connect(Path(db_path), create=False)
        except (DatastoreUnreadableError, sqlite3.Error) as exc:
            logger.debug("pipeline_recent_names_unreadable", error=type(exc).__name__)
            return {}
        try:
            return read_names(conn, conversation_ids)
        except sqlite3.Error as exc:
            logger.warning("pipeline_recent_names_failed", error=type(exc).__name__, conversations=len(conversation_ids))
            return {}
        finally:
            conn.close()

    return resolve


def error_class(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    return text.split(":", 1)[0].strip()[:ERROR_CLASS_CHARS] or None


@dataclass
class _Row:

    plugin: str
    kind: str
    area: Area
    conversation_id: Optional[str]
    family: Optional[str]
    trigger: Optional[str]
    finished_at: float
    duration_ms: float
    outcome: str
    error: Optional[str]
    events: int
    runs: int = 1

    def public(self) -> Dict[str, Any]:
        return {"plugin": self.plugin, "kind": self.kind, "scope": self.area.scope,
                "session_uuid": self.area.session_uuid, "session": self.area.session,
                "project_id": self.area.project_id, "project": self.area.project,
                "conversation_id": self.conversation_id, "family": self.family, "trigger": self.trigger,
                "finished_at": self.finished_at, "duration_ms": self.duration_ms, "runs": self.runs,
                "events": self.events, "outcome": self.outcome, "error": self.error}


class RecentRuns:

    def __init__(self, resolve: Optional[Resolver] = None, *, limit: int = ROW_LIMIT,
                 wall: Callable[[], float] = time.time, clock: Callable[[], float] = time.monotonic,
                 name_ttl: float = NAME_TTL_SECONDS, negative_ttl: float = NEGATIVE_TTL_SECONDS,
                 name_cache_limit: int = NAME_CACHE_LIMIT) -> None:
        self._resolve = resolve or no_names
        self._limit = max(1, int(limit))
        self._wall = wall
        self._clock = clock
        self._ttl = name_ttl
        self._negative_ttl = negative_ttl
        self._cache_limit = max(1, int(name_cache_limit))
        self._lock = threading.Lock()
        self._rows: "OrderedDict[Tuple[str, str, str], _Row]" = OrderedDict()
        self._names: "OrderedDict[str, Tuple[float, Area]]" = OrderedDict()

    def _fresh(self, cached: Optional[Tuple[float, Area]], now: float) -> bool:
        if cached is None:
            return False
        ttl = self._negative_ttl if cached[1] is MACHINE else self._ttl
        return now - cached[0] <= ttl

    def _stale(self, conversation_ids: Iterable[str]) -> List[str]:
        now = self._clock()
        out: List[str] = []
        with self._lock:
            for conv in conversation_ids:
                if not conv or conv in out:
                    continue
                if not self._fresh(self._names.get(conv), now):
                    out.append(conv)
        return out

    def prepare(self, conversation_ids: Iterable[str]) -> None:
        stale = self._stale(conversation_ids)
        if not stale:
            return
        try:
            found = self._resolve(stale)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pipeline_recent_resolve_failed", error=type(exc).__name__, conversations=len(stale))
            found = {}
        now = self._clock()
        with self._lock:
            for conv in stale:
                self._names[conv] = (now, found.get(conv) or MACHINE)
                self._names.move_to_end(conv)
            while len(self._names) > self._cache_limit:
                self._names.popitem(last=False)

    def cached_area(self, conversation_id: Optional[str]) -> Area:
        return self.cached_lookup(conversation_id) or MACHINE

    def cached_lookup(self, conversation_id: Optional[str]) -> Optional[Area]:
        if not conversation_id:
            return None
        with self._lock:
            cached = self._names.get(conversation_id)
            if not self._fresh(cached, self._clock()):
                return None
        return cached[1]

    def _put(self, key: Tuple[str, str, str], row: _Row) -> None:
        with self._lock:
            held = self._rows.get(key)
            if held is not None:
                row.runs = held.runs + 1
            self._rows[key] = row
            self._rows.move_to_end(key)
            while len(self._rows) > self._limit:
                self._rows.popitem(last=False)

    def record(self, *, plugin_id: str, conversation_id: Optional[str], family: Optional[str], trigger: Optional[str],
               duration_s: float, outcome: str, events: int = 0, error: Optional[str] = None,
               area: Optional[Area] = None) -> None:
        if outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome {outcome!r}")
        if area is None:
            area = self.cached_area(conversation_id)
        row = _Row(plugin_id, KIND_DELIVERY, area, conversation_id, family, trigger, self._wall(),
                   round(max(0.0, duration_s) * 1000.0, 1), outcome, error_class(error), int(events))
        self._put((area.key, plugin_id, KIND_DELIVERY), row)

    def record_rebuild(self, *, plugin_id: str, duration_s: float, outcome: str, error: Optional[str] = None) -> None:
        if outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome {outcome!r}")
        row = _Row(plugin_id, KIND_REBUILD, MACHINE, None, None, KIND_REBUILD, self._wall(),
                   round(max(0.0, duration_s) * 1000.0, 1), outcome, error_class(error), 0)
        self._put((MACHINE.key, plugin_id, KIND_REBUILD), row)

    def rows(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [row.public() for row in reversed(self._rows.values())]
