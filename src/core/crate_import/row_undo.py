
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Sequence, Set, Tuple

import structlog

from src.core.crate_import import row_journal as rj
from src.core.crate_import.keyrules import REF, RULES
from src.core.inventory.model import MAIN_STORE

logger = structlog.get_logger()

WHY_CHANGED = "changed since the import"
WHY_REFERENCED = "something added since points at it"
WHY_RECREATED = "was written again since"
_CHUNK = 400


@dataclass
class StorePlan:

    store: str
    deletes: Dict[str, List[list]] = field(default_factory=dict)
    restores: Dict[str, List[Tuple[list, list]]] = field(default_factory=dict)
    reverts: Dict[str, List[Tuple[list, list]]] = field(default_factory=dict)
    kept: List[Dict[str, str]] = field(default_factory=list)

    def count(self) -> int:
        return sum(len(v) for v in self.deletes.values())


@dataclass
class RowsPlan:

    stores: List[StorePlan] = field(default_factory=list)
    blockers: List[Tuple[str, str]] = field(default_factory=list)


@dataclass
class RowsReport:

    deleted: int = 0
    restored: int = 0
    reverted: int = 0
    kept: List[Dict[str, str]] = field(default_factory=list)


def _key_tuple(key: Sequence[Any]) -> Tuple[Any, ...]:
    return tuple(key)


def _row_label(tbl: str, key: Sequence[Any]) -> str:
    return f"{tbl} row {','.join(str(k) for k in key)}"


def _edges(conn: sqlite3.Connection, store: str, tables: Dict[str, Any]) -> List[Tuple[str, str, str, str]]:
    names = [r[0] for r in conn.execute("SELECT name FROM main.sqlite_master WHERE type = 'table'")]
    out: Set[Tuple[str, str, str, str]] = set()
    for child in names:
        for fk in conn.execute(f"PRAGMA main.foreign_key_list({rj.quote(child)})").fetchall():
            if fk[3] and fk[4]:
                out.add((child, fk[3], fk[2], fk[4]))
    if store == MAIN_STORE:
        for key, rules in RULES.items():
            child = key[len(MAIN_STORE) + 1:] if key.startswith(MAIN_STORE + ".") else None
            for column, rule in rules.items():
                if child and rule.kind == REF and "#" not in column and rule.target and "." in rule.target and child in names:
                    parent, _, pcol = rule.target.partition(".")
                    if parent in names:
                        out.add((child, column, parent, pcol))
    return sorted(out)


def _value(conn: sqlite3.Connection, table: Dict[str, Any], tbl: str, key: Sequence[Any], column: str) -> Any:
    row = conn.execute(f"SELECT {rj.quote(column)} FROM main.{rj.quote(tbl)} WHERE {rj.where_key(table)}", tuple(key)).fetchone()
    return None if row is None else row[0]


def _referenced_by_others(conn: sqlite3.Connection, edges: List[Tuple[str, str, str, str]], tables: Dict[str, Any],
                          cand: Dict[str, Set[Tuple[Any, ...]]], tbl: str, key: Tuple[Any, ...]) -> bool:
    for child, column, parent, pcol in edges:
        if parent != tbl or child not in tables and not _has_table(conn, child):
            continue
        value = _value(conn, tables[tbl], tbl, key, pcol)
        if value is None:
            continue
        pk = tables[child]["pk"] if child in tables else _pk_of(conn, child)
        select = ", ".join(rj.quote(c) for c in pk) if pk else "rowid"
        for found in conn.execute(f"SELECT {select} FROM main.{rj.quote(child)} WHERE {rj.quote(column)} IS ?", (value,)):
            if (child, parent) == (tbl, tbl) and _key_tuple(found) == key:
                continue
            if _key_tuple(found) not in cand.get(child, set()):
                return True
    return False


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM main.sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def _pk_of(conn: sqlite3.Connection, name: str) -> List[str]:
    info = conn.execute(f"PRAGMA main.table_info({rj.quote(name)})").fetchall()
    return [r[1] for r in sorted((r for r in info if r[5] > 0), key=lambda r: r[5])]


def plan_store(path: Path, store: str, tables: Dict[str, Any]) -> StorePlan:
    out = StorePlan(store)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30.0)
    try:
        cand: Dict[str, Set[Tuple[Any, ...]]] = {}
        for tbl, table in tables.items():
            if not _has_table(conn, tbl):
                continue
            for key, expected in table["ins"]:
                now = rj.current_hash(conn, tbl, table, key)
                if now is None:
                    continue
                if now != expected:
                    out.kept.append({"what": _row_label(tbl, key), "why": WHY_CHANGED})
                else:
                    cand.setdefault(tbl, set()).add(_key_tuple(key))
            for key, old, after in table["rev"]:
                now = rj.current_hash(conn, tbl, table, key)
                if after is None:
                    (out.kept.append({"what": _row_label(tbl, key), "why": WHY_RECREATED}) if now is not None
                     else out.restores.setdefault(tbl, []).append((key, old)))
                elif now == after:
                    out.reverts.setdefault(tbl, []).append((key, old))
                elif now is not None:
                    out.kept.append({"what": _row_label(tbl, key), "why": WHY_CHANGED})
        edges = _edges(conn, store, tables)
        changed = True
        while changed:  # something else
            changed = False
            for tbl in list(cand):
                for key in sorted(cand[tbl], key=repr):
                    if _referenced_by_others(conn, edges, tables, cand, tbl, key):
                        cand[tbl].discard(key)
                        out.kept.append({"what": _row_label(tbl, key), "why": WHY_REFERENCED})
                        changed = True
        out.deletes = {tbl: [list(k) for k in keys] for tbl, keys in cand.items() if keys}
    finally:
        conn.close()
    return out


def plan(state: Path, record: Dict[str, Any]) -> RowsPlan:
    out = RowsPlan()
    if not record.get("complete"):
        out.blockers.append(("record_incomplete", "this restore was finished after an interruption, so its record of the rows it wrote may be missing some"))
        return out
    if not record.get("sealed"):
        out.blockers.append(("record_incomplete", "this restore's record is not finished, so a row it wrote cannot be told from one changed since"))
        return out
    for store, tables in (record.get("stores") or {}).items():
        try:
            out.stores.append(plan_store(rj.store_path(state, store), store, tables))
        except sqlite3.Error as exc:
            out.blockers.append(("database_unreadable", f"the {store} database cannot be read now ({type(exc).__name__})"))
    return out


def _insert(conn: sqlite3.Connection, tbl: str, table: Dict[str, Any], old: list) -> None:
    live = {r[1] for r in conn.execute(f"PRAGMA main.table_info({rj.quote(tbl)})")}
    pairs = [(c, v) for c, v in zip(table["cols"], rj.decode_row(old)) if c in live]
    names = ", ".join(rj.quote(c) for c, _ in pairs)
    conn.execute(f"INSERT INTO main.{rj.quote(tbl)} ({names}) VALUES ({', '.join('?' for _ in pairs)})", tuple(v for _, v in pairs))


def _revert(conn: sqlite3.Connection, tbl: str, table: Dict[str, Any], key: list, old: list) -> None:
    live = {r[1] for r in conn.execute(f"PRAGMA main.table_info({rj.quote(tbl)})")}
    pairs = [(c, v) for c, v in zip(table["cols"], rj.decode_row(old)) if c in live and c not in table["pk"]]
    if pairs:
        sets = ", ".join(f"{rj.quote(c)} = ?" for c, _ in pairs)
        conn.execute(f"UPDATE main.{rj.quote(tbl)} SET {sets} WHERE {rj.where_key(table)}", (*[v for _, v in pairs], *key))


def apply_store(path: Path, plan_: StorePlan, tables: Dict[str, Any]) -> Tuple[int, int, int]:
    conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    deleted = restored = reverted = 0
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("PRAGMA defer_foreign_keys=ON")
            for tbl, rows in plan_.restores.items():
                for key, old in rows:
                    _insert(conn, tbl, tables[tbl], old)
                    restored += 1
            for tbl, rows in plan_.reverts.items():
                for key, old in rows:
                    _revert(conn, tbl, tables[tbl], key, old)
                    reverted += 1
            for tbl, keys in plan_.deletes.items():
                for key in reversed(keys):
                    conn.execute(f"DELETE FROM main.{rj.quote(tbl)} WHERE {rj.where_key(tables[tbl])}", tuple(key))
                    deleted += 1
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    return deleted, restored, reverted


def apply(state: Path, record: Dict[str, Any], plan_: RowsPlan) -> RowsReport:
    report = RowsReport()
    ordered = sorted(plan_.stores, key=lambda s: s.store == MAIN_STORE)
    for sp in ordered:
        d, r, c = apply_store(rj.store_path(state, sp.store), sp, record["stores"][sp.store])
        report.deleted, report.restored, report.reverted = report.deleted + d, report.restored + r, report.reverted + c
        report.kept += sp.kept
    return report
