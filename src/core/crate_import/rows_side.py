
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import structlog

from src.core.automations.models import FAILED, LIVE_STATUSES
from src.core.crate_import import idmap as ids_keys
from src.core.crate_import import policy, row_journal
from src.core.crate_import.idmap import IdMap
from src.core.crate_import.model import W_AUTOMATION_DISABLED, W_DANGLING_REF, W_SIDE_STORE_ABSENT, Collector
from src.core.crate_import.rows_write import TableCounts
from src.core.inventory.registry_side import ATTENTION, AUTOMATIONS, BOOKMARKS, STATS, side_db_path
from src.core.stats.plugin.extract import project_key

logger = structlog.get_logger()

BOOKMARK_TABLE = f"{BOOKMARKS}.bookmarks"
ATTENTION_TABLE = f"{ATTENTION}.attention_events"
AUTOMATION_TABLES: Tuple[str, ...] = tuple(f"{AUTOMATIONS}.{t}" for t in ("automations", "automation_changes", "runs", "run_sessions"))
ANNOTATION_TABLE = f"{STATS}.stats_annotations"
BY_STORE: Dict[str, Tuple[str, ...]] = {
    BOOKMARKS: (BOOKMARK_TABLE,), ATTENTION: (ATTENTION_TABLE,), AUTOMATIONS: AUTOMATION_TABLES, STATS: (ANNOTATION_TABLE,)}
TABLES: Tuple[str, ...] = policy.SIDE_TABLES
IMPORTED_SUFFIX = " (imported)"
RUN_REASON = "imported_run_was_not_finished"
_REF_SESSION_KEYS = ("session_uuid",)


class _Ctx:

    def __init__(self, main: sqlite3.Connection, idmap: IdMap, col: Collector) -> None:
        self.main, self.idmap, self.col = main, idmap, col
        self.counts: Dict[str, TableCounts] = {}

    def table(self, key: str) -> TableCounts:
        return self.counts.setdefault(key, TableCounts())

    def session(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        mapped = self.idmap.get(ids_keys.SESSION_UUIDS, value)
        if mapped is not None:
            return str(mapped)
        found = self.main.execute("SELECT 1 FROM sessions WHERE session_uuid = ?", (value,)).fetchone()
        return str(value) if found is not None else None

    def row_id(self, value: Any) -> Optional[int]:
        mapped = self.idmap.get(ids_keys.SESSIONS, value) if value is not None else None
        return int(mapped) if mapped is not None else None


def _insert(conn: sqlite3.Connection, table: str, values: Dict[str, Any]) -> int:
    names = ", ".join(f'"{c}"' for c in values)
    return int(conn.execute(f"INSERT INTO {table} ({names}) VALUES ({', '.join('?' for _ in values)})", tuple(values.values())).lastrowid)


def _has(conn: sqlite3.Connection, table: str, where: Dict[str, Any]) -> bool:
    clause = " AND ".join(f'"{c}" IS ?' for c in where)
    return conn.execute(f"SELECT 1 FROM {table} WHERE {clause} LIMIT 1", tuple(where.values())).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> List[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _own(conn: sqlite3.Connection, table: str, row: Dict[str, Any], *drop: str) -> Dict[str, Any]:
    names = _columns(conn, table)
    return {c: v for c, v in row.items() if c in names and c not in drop}


def _bookmarks(conn: sqlite3.Connection, ctx: _Ctx, rows: Iterable[Dict[str, Any]]) -> None:
    counts = ctx.table(BOOKMARK_TABLE)
    for source in rows:
        row = dict(source)
        row["session_uuid"] = ctx.session(row.get("session_uuid"))
        if row["session_uuid"] is None:
            counts.skip("session_not_here")
            continue
        row["session_row_id"] = ctx.row_id(row.get("session_row_id"))
        if _has(conn, "bookmarks", {"entry_uuid": row.get("entry_uuid")}):
            counts.present += 1
            continue
        _insert(conn, "bookmarks", _own(conn, "bookmarks", row, "id"))
        counts.inserted += 1


def _attention(conn: sqlite3.Connection, ctx: _Ctx, rows: Iterable[Dict[str, Any]]) -> None:
    counts = ctx.table(ATTENTION_TABLE)
    for source in rows:
        row = _own(conn, "attention_events", dict(source), "id")
        row["session_uuid"] = ctx.session(row.get("session_uuid"))
        if row["session_uuid"] is None:
            counts.skip("session_not_here")
            continue
        if _has(conn, "attention_events", row):
            counts.present += 1
            continue
        _insert(conn, "attention_events", row)
        counts.inserted += 1


def rekey_target(node: Any, ctx: _Ctx) -> Any:
    if isinstance(node, dict):
        for key, value in list(node.items()):
            if key in _REF_SESSION_KEYS and isinstance(value, str):
                node[key] = ctx.session(value) or value
            elif key == "project_id" and value is not None:
                mapped = ctx.idmap.get(ids_keys.PROJECTS, value)
                node[key] = int(mapped) if mapped is not None else value
            else:
                rekey_target(value, ctx)
    elif isinstance(node, list):
        for value in node:
            rekey_target(value, ctx)
    return node


def _free_name(conn: sqlite3.Connection, name: str) -> Tuple[str, str]:
    candidate, n = name, 1
    while _has(conn, "automations", {"name_key": candidate.casefold()}):
        n += 1
        candidate = name + (IMPORTED_SUFFIX if n == 2 else f" (imported {n - 1})")
    return candidate, candidate.casefold()


def _automations(conn: sqlite3.Connection, ctx: _Ctx, sanitized: Dict[str, List[Dict[str, Any]]]) -> None:
    counts = ctx.table(AUTOMATION_TABLES[0])
    for source in sanitized.get(AUTOMATION_TABLES[0], []):
        row = dict(source)
        if _has(conn, "automations", {"automation_id": row.get("automation_id")}):
            counts.present += 1
            continue
        project = row.get("project_id")
        row["project_id"] = ctx.idmap.get(ids_keys.PROJECTS, project) if project is not None else None
        if project is not None and row["project_id"] is None:
            ctx.col.warn(W_DANGLING_REF, f"{AUTOMATION_TABLES[0]}.project_id")
        try:
            target = rekey_target(json.loads(row["target"]), ctx)
            row["target"] = json.dumps(target)
        except (TypeError, ValueError):
            counts.reasons["target_unreadable"] = counts.reasons.get("target_unreadable", 0) + 1
        row.update(enabled=0, next_fire_at=None, retry_due_at=None, retry_attempt=0, seed_key=None)
        row["name"], row["name_key"] = _free_name(conn, str(row.get("name") or row.get("automation_id")))
        _insert(conn, "automations", _own(conn, "automations", row))
        counts.inserted += 1
        ctx.col.warn(W_AUTOMATION_DISABLED, str(row["automation_id"]))
    _automation_children(conn, ctx, sanitized)


def _automation_children(conn: sqlite3.Connection, ctx: _Ctx, sanitized: Dict[str, List[Dict[str, Any]]]) -> None:
    changes, runs, links = (ctx.table(AUTOMATION_TABLES[i]) for i in (1, 2, 3))
    for source in sanitized.get(AUTOMATION_TABLES[1], []):
        row = _own(conn, "automation_changes", dict(source), "seq")
        if not _has(conn, "automations", {"automation_id": row.get("automation_id")}):
            changes.skip("automation_not_here")
        elif _has(conn, "automation_changes", row):
            changes.present += 1
        else:
            _insert(conn, "automation_changes", row)
            changes.inserted += 1
    for source in sanitized.get(AUTOMATION_TABLES[2], []):
        row = _own(conn, "runs", dict(source), "seq")
        if not _has(conn, "automations", {"automation_id": row.get("automation_id")}):
            runs.skip("automation_not_here")
        elif _has(conn, "runs", {"run_id": row.get("run_id")}):
            runs.present += 1
        else:
            if row.get("status") in LIVE_STATUSES:
                row.update(status=FAILED, reason=RUN_REASON)
            row["boot_id"] = None
            _insert(conn, "runs", row)
            runs.inserted += 1
    for source in sanitized.get(AUTOMATION_TABLES[3], []):
        row = _own(conn, "run_sessions", dict(source))
        row["session_uuid"] = ctx.session(row.get("session_uuid"))
        row["session_row_id"] = ctx.row_id(row.get("session_row_id"))
        if row["session_uuid"] is None or not _has(conn, "runs", {"run_id": row.get("run_id")}):
            links.skip("run_or_session_not_here")
        elif _has(conn, "run_sessions", {"run_id": row["run_id"], "session_uuid": row["session_uuid"]}):
            links.present += 1
        else:
            _insert(conn, "run_sessions", row)
            links.inserted += 1


def _annotations(conn: sqlite3.Connection, ctx: _Ctx, rows: Iterable[Dict[str, Any]], new_key: str) -> None:
    counts = ctx.table(ANNOTATION_TABLE)
    for source in rows:
        row = dict(source)
        if _has(conn, "stats_annotations", {"id": row.get("id")}):
            counts.present += 1
            continue
        try:
            scope = json.loads(row.get("scope_json") or "{}")
        except ValueError:
            scope = {}
        if isinstance(scope, dict) and isinstance(scope.get("project"), str):
            scope["project"] = new_key
            row["scope_json"] = json.dumps(scope, sort_keys=True)
        _insert(conn, "stats_annotations", _own(conn, "stats_annotations", row))
        counts.inserted += 1


def write_side(state: Path, main: sqlite3.Connection, idmap: IdMap, sanitized: Dict[str, List[Dict[str, Any]]], col: Collector, *,
               new_root: str, journal: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, TableCounts]:
    ctx = _Ctx(main, idmap, col)
    for store, tables in BY_STORE.items():
        if not any(sanitized.get(t) for t in tables):
            continue
        path = side_db_path(state, store)
        if not path.is_file():
            col.warn(W_SIDE_STORE_ABSENT, store)
            for t in tables:
                for _ in sanitized.get(t, []):
                    ctx.table(t).skip("store_absent")
            continue
        conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            tracked = row_journal.start(conn)
            if store == BOOKMARKS:
                _bookmarks(conn, ctx, sanitized.get(BOOKMARK_TABLE, []))
            elif store == ATTENTION:
                _attention(conn, ctx, sanitized.get(ATTENTION_TABLE, []))
            elif store == AUTOMATIONS:
                _automations(conn, ctx, sanitized)
            else:
                _annotations(conn, ctx, sanitized.get(ANNOTATION_TABLE, []), project_key(new_root))
            if journal is not None:
                journal[store] = row_journal.finish(conn, tracked)
            conn.execute("COMMIT")
        except sqlite3.Error:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
    return ctx.counts
