
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

import structlog

from src.core.crate_import import idmap as ids
from src.core.crate_import import keymap
from src.core.crate_import.keyrules import REF, rule_for
from src.core.crate_import.model import W_DANGLING_REF, Collector
from src.core.inventory.model import MAIN_STORE
from src.core.work.file_refs import FileHome

logger = structlog.get_logger()

ONE_PER_KEY = frozenset(f"{MAIN_STORE}.{t}" for t in (
    "companies", "projects", "sessions", "session_notes", "session_groups", "layouts", "lineage_nodes", "conversation_index"))


@dataclass
class TableCounts:

    inserted: int = 0
    present: int = 0
    kept_local: int = 0
    skipped: int = 0
    reasons: Dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.skipped += 1
        self.reasons[reason] = self.reasons.get(reason, 0) + 1

    def as_json(self) -> Dict[str, Any]:
        return {"inserted": self.inserted, "present": self.present, "kept_local": self.kept_local, "skipped": self.skipped,
                "reasons": dict(self.reasons)}


@dataclass
class WriteCtx:

    conn: sqlite3.Connection
    idmap: ids.IdMap
    own: bool
    col: Collector
    counts: Dict[str, TableCounts] = field(default_factory=dict)
    created: Dict[str, List[Any]] = field(default_factory=dict)
    shapes: Dict[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = field(default_factory=dict)
    files: Optional[FileHome] = None

    def table_counts(self, key: str) -> TableCounts:
        return self.counts.setdefault(key, TableCounts())

    def columns(self, table: str) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
        if table not in self.shapes:
            info = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
            self.shapes[table] = (tuple(r[1] for r in info), tuple(r[1] for r in info if r[3] and r[4] is None and r[5] == 0))
        return self.shapes[table]


def map_refs(ctx: WriteCtx, key: str, table: str, row: Dict[str, Any]) -> Optional[str]:
    _all, required = ctx.columns(table)
    store = MAIN_STORE
    for column in list(row):
        rule = rule_for(store, table, column)
        if rule is None or rule.kind != REF or row[column] is None:
            continue
        mapped = ids.ref(ctx.conn, ctx.idmap, rule, row[column])
        if mapped is not None:
            row[column] = mapped
        elif column in required:
            return f"dangling_{column}"
        else:
            row[column] = None
            ctx.col.warn(W_DANGLING_REF, f"{key}.{column}")
    return None


def insert_row(ctx: WriteCtx, table: str, values: Mapping[str, Any], *, ignore: bool) -> Tuple[bool, Optional[int]]:
    columns = ", ".join(f'"{c}"' for c in values)
    marks = ", ".join("?" for _ in values)
    ctx.conn.execute("SAVEPOINT crate_row")
    try:
        cur = ctx.conn.execute(f"INSERT {'OR IGNORE ' if ignore else ''}INTO {table} ({columns}) VALUES ({marks})", tuple(values.values()))
    except sqlite3.IntegrityError:
        ctx.conn.execute("ROLLBACK TO crate_row")
        ctx.conn.execute("RELEASE crate_row")
        raise
    ctx.conn.execute("RELEASE crate_row")
    return (cur.rowcount > 0, int(cur.lastrowid) if cur.rowcount > 0 else None)


def own_columns(ctx: WriteCtx, table: str, row: Mapping[str, Any]) -> Dict[str, Any]:
    names, _required = ctx.columns(table)
    return {c: v for c, v in row.items() if c in names}


def write_generic(ctx: WriteCtx, key: str, rows: List[Dict[str, Any]]) -> None:
    store, _, table = key.rpartition(".")
    counts = ctx.table_counts(key)
    natural = keymap.NATURAL_KEYS.get(key) if key in ONE_PER_KEY else None
    self_rule = rule_for(store, table, "id")
    has_self = self_rule is not None and self_rule.kind == "self"
    for source in rows:
        row = dict(source)
        old_id = row.pop("id", None) if has_self else None
        if not has_self and "id" in row and rule_for(store, table, "id") is None:
            row.pop("id")
        if natural is not None:
            here = _find(ctx, table, {c: row.get(c) for c in natural})
            if here is not None:
                if has_self and old_id is not None:
                    ctx.idmap.put(key, old_id, here["id"])
                same = all(here.get(c) == row.get(c) for c in set(keymap.comparable(store, table, here)) & set(keymap.comparable(store, table, row)))
                counts.present += 1 if same else 0
                counts.kept_local += 0 if same else 1
                continue
        reason = map_refs(ctx, key, table, row)
        if reason is not None:
            counts.skip(reason)
            continue
        values = own_columns(ctx, table, row)
        if natural is None and _identical_exists(ctx, table, values):
            counts.present += 1
            continue
        try:
            inserted, rowid = insert_row(ctx, table, values, ignore=natural is None)
        except sqlite3.IntegrityError as exc:
            logger.info("crate_import_row_refused", table=key, error=str(exc)[:120])
            counts.skip("refused_by_unique_rule")
            continue
        if not inserted:
            counts.present += 1
            continue
        counts.inserted += 1
        if has_self and old_id is not None and rowid is not None:
            ctx.idmap.put(key, old_id, rowid)
            ctx.created.setdefault(key, []).append(rowid)


def _identical_exists(ctx: WriteCtx, table: str, values: Mapping[str, Any]) -> bool:
    if not values:
        return False
    where = " AND ".join(f'"{c}" IS ?' for c in values)
    try:
        return ctx.conn.execute(f'SELECT 1 FROM "{table}" WHERE {where} LIMIT 1', tuple(values.values())).fetchone() is not None
    except sqlite3.Error:
        return False


def _find(ctx: WriteCtx, table: str, key: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    if any(v is None for v in key.values()):
        return None
    where = " AND ".join(f"{c} = ?" for c in key)
    found = ctx.conn.execute(f"SELECT * FROM {table} WHERE {where} LIMIT 1", tuple(key.values())).fetchone()
    return dict(found) if found is not None else None
