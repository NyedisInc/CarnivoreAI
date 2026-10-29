
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.crate_import import ledger
from src.core.db import connect, db_path_for, transaction
from src.core.inventory.model import MAIN_STORE

logger = structlog.get_logger()

LOG_TABLE = "_crate_undo"
RECORD_VERSION = 1
_SKIP = frozenset({"meta"})
_MAX_COLUMNS = 120


class JournalError(Exception):
    """The journal could not be started (a table too wide to log). The import is refused before it writes anything."""


@dataclass(frozen=True)
class Table:

    name: str
    cols: Tuple[str, ...]
    pk: Tuple[str, ...]


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def tracked_tables(conn: sqlite3.Connection) -> List[Table]:
    rows = conn.execute("SELECT name, sql FROM main.sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    virtual = [r[0] for r in rows if (r[1] or "").lstrip().upper().startswith("CREATE VIRTUAL")]
    out: List[Table] = []
    for name, sql in rows:
        if name in _SKIP or name in virtual or any(name.startswith(v + "_") for v in virtual) or (sql or "").lstrip().upper().startswith("CREATE VIRTUAL"):
            continue
        info = conn.execute(f"PRAGMA main.table_info({quote(name)})").fetchall()
        pk = tuple(r[1] for r in sorted((r for r in info if r[5] > 0), key=lambda r: r[5]))
        out.append(Table(name, tuple(r[1] for r in info), pk))
    return out


def _key_expr(table: Table, ref: str) -> str:
    return "json_array(" + ", ".join(f"{ref}.{quote(c)}" for c in table.pk or ("rowid",)) + ")"


def _row_expr(table: Table) -> str:
    return "json_array(" + ", ".join(
        f"json_array(typeof(OLD.{quote(c)}), CASE typeof(OLD.{quote(c)}) WHEN 'blob' THEN hex(OLD.{quote(c)}) ELSE OLD.{quote(c)} END)"
        for c in table.cols) + ")"


def start(conn: sqlite3.Connection) -> List[Table]:
    tables = tracked_tables(conn)
    conn.execute(f"CREATE TEMP TABLE IF NOT EXISTS {LOG_TABLE} (seq INTEGER PRIMARY KEY AUTOINCREMENT, op TEXT NOT NULL, tbl TEXT NOT NULL, "
                 "key TEXT NOT NULL, old TEXT)")
    conn.execute(f"DELETE FROM temp.{LOG_TABLE}")
    for t in tables:
        if len(t.cols) > _MAX_COLUMNS:
            raise JournalError(f"table {t.name} has {len(t.cols)} columns")
        ins = f"INSERT INTO temp.{LOG_TABLE} (op, tbl, key, old) VALUES"
        literal = t.name.replace("'", "''")
        conn.execute(f"CREATE TEMP TRIGGER IF NOT EXISTS {quote('_cu_i_' + t.name)} AFTER INSERT ON main.{quote(t.name)} "
                     f"BEGIN {ins} ('i', '{literal}', {_key_expr(t, 'NEW')}, NULL); END")
        for op, event in (("d", "DELETE"), ("u", "UPDATE")):
            conn.execute(f"CREATE TEMP TRIGGER IF NOT EXISTS {quote('_cu_' + op + '_' + t.name)} BEFORE {event} ON main.{quote(t.name)} "
                         f"BEGIN {ins} ('{op}', '{literal}', {_key_expr(t, 'OLD')}, {_row_expr(t)}); END")
    return tables


def decode_row(typed: Sequence[Sequence[Any]]) -> List[Any]:
    return [bytes.fromhex(v) if t == "blob" else v for t, v in typed]


def row_hash(values: Sequence[Any]) -> str:
    flat = [("b:" + v.hex()) if isinstance(v, (bytes, bytearray)) else v for v in values]
    return hashlib.sha256(json.dumps(flat, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()[:20]


def finish(conn: sqlite3.Connection, tables: Sequence[Table]) -> Dict[str, Any]:
    by_name = {t.name: t for t in tables}
    state: Dict[Tuple[str, str], Tuple[str, Optional[list]]] = {}
    order: List[Tuple[str, str]] = []
    for op, tbl, key, old in conn.execute(f"SELECT op, tbl, key, old FROM temp.{LOG_TABLE} ORDER BY seq").fetchall():
        k = (tbl, key)
        was = state.get(k)
        if op == "i":
            if was is None:
                state[k] = ("ins", None)
                order.append(k)
            elif was[0] == "gone":
                state[k] = ("rev", was[1])
        elif op == "u":
            if was is None:
                state[k] = ("rev", json.loads(old))
                order.append(k)
        elif was is None:
            state[k] = ("gone", json.loads(old))
            order.append(k)
        elif was[0] == "ins":
            del state[k]
            order.remove(k)
        elif was[0] == "rev":
            state[k] = ("gone", was[1])
    out: Dict[str, Any] = {}
    for k in order:
        tbl, key = k
        kind, old = state[k]
        t = by_name[tbl]
        entry = out.setdefault(tbl, {"pk": list(t.pk), "cols": list(t.cols), "ins": [], "rev": []})
        if kind == "ins":
            entry["ins"].append([json.loads(key), None])
        else:
            entry["rev"].append([json.loads(key), old, None])
    return out


def record_of(stores: Dict[str, Any], *, complete: bool = True) -> Dict[str, Any]:
    return {"v": RECORD_VERSION, "complete": complete, "sealed": False, "stores": stores}


def where_key(table: Dict[str, Any]) -> str:
    return " AND ".join(f"{quote(c)} IS ?" for c in table["pk"] or ["rowid"])


def current_hash(conn: sqlite3.Connection, tbl: str, table: Dict[str, Any], key: Sequence[Any]) -> Optional[str]:
    cols = ", ".join(quote(c) for c in table["cols"])
    row = conn.execute(f"SELECT {cols} FROM main.{quote(tbl)} WHERE {where_key(table)}", tuple(key)).fetchone()
    return None if row is None else row_hash(list(row))


def store_path(state: Path, store: str) -> Path:
    if store == MAIN_STORE:
        return db_path_for(state)
    from src.core.inventory.registry_side import side_db_path

    return side_db_path(state, store)


def _seal_store(path: Path, tables: Dict[str, Any]) -> None:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30.0)
    try:
        for tbl, table in tables.items():
            for item in table["ins"]:
                item[1] = current_hash(conn, tbl, table, item[0])
            for item in table["rev"]:
                item[2] = current_hash(conn, tbl, table, item[0])
    finally:
        conn.close()


def seal(state: Path, import_id: str) -> None:
    """Add the after-hash of every journaled row (module docstring), once. Blocking; one write transaction on ``carnivore.db``.

    A store that cannot be opened now keeps null hashes, which an undo reads as "cannot tell if it changed" and refuses. Safe to run twice.
    """
    conn = connect(db_path_for(state), create=False)
    try:
        record = ledger.read_undo(conn, import_id)
        if record is None or record.get("sealed"):
            return
        for store, tables in (record.get("stores") or {}).items():
            try:
                _seal_store(store_path(state, store), tables)
            except sqlite3.Error as exc:
                logger.warning("crate_import_seal_store_failed", store=store, error=type(exc).__name__)
        record["sealed"] = True
        with transaction(conn):
            ledger.write_undo(conn, import_id, record)
    finally:
        conn.close()


def merge_store(state: Path, import_id: str, store: str, tables: Dict[str, Any]) -> None:
    if not tables:
        return
    conn = connect(db_path_for(state), create=False)
    try:
        with transaction(conn):
            record = ledger.read_undo(conn, import_id)
            if record is None:
                return
            record["stores"][store] = tables
            ledger.write_undo(conn, import_id, record)
    finally:
        conn.close()


def merge_fields(state: Path, import_id: str, **fields: Any) -> None:
    conn = connect(db_path_for(state), create=False)
    try:
        with transaction(conn):
            record = ledger.read_undo(conn, import_id)
            if record is None:
                return
            record.update(fields)
            ledger.write_undo(conn, import_id, record)
    finally:
        conn.close()


def mark_incomplete(state: Path, import_id: str) -> None:
    conn = connect(db_path_for(state), create=False)
    try:
        with transaction(conn):
            record = ledger.read_undo(conn, import_id)
            if record is not None and record.get("complete"):
                record["complete"] = False
                ledger.write_undo(conn, import_id, record)
    finally:
        conn.close()


__all__ = ["JournalError", "Table", "current_hash", "finish", "mark_incomplete", "merge_store", "record_of", "row_hash", "seal", "start",
           "store_path", "tracked_tables", "decode_row", "merge_fields"]
