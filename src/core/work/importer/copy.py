
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

from src.core.work import tables
from src.core.work.importer.errors import WorkImportDeferred
from src.core.work.work_ladder import statements
from src.core.work.work_ladder.w1 import IMPORTS, TABLES, TRIGGERS

LEGACY = "legacy"


@dataclass
class CopyResult:

    counts: Dict[str, int] = field(default_factory=dict)
    digests: Dict[str, str] = field(default_factory=dict)


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def columns(conn: sqlite3.Connection, schema: str, table: str) -> List[str]:
    return [r[1] for r in conn.execute(f"PRAGMA {schema}.table_info({quote(table)})").fetchall()]


def has_rowid(conn: sqlite3.Connection, schema: str, table: str) -> bool:
    row = conn.execute(f"SELECT sql FROM {schema}.sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    return row is not None and "WITHOUT ROWID" not in (row[0] or "").upper()


def _order(conn: sqlite3.Connection, schema: str, table: str, rowid: bool) -> str:
    if rowid:
        return "rowid"
    pk = sorted((r[5], r[1]) for r in conn.execute(f"PRAGMA {schema}.table_info({quote(table)})").fetchall() if r[5])
    return ", ".join(quote(name) for _, name in pk)


def digest(conn: sqlite3.Connection, schema: str, table: str, cols: Sequence[str], rowid: bool) -> Tuple[int, str]:
    return digest_query(conn, digest_sql(conn, schema, table, cols, rowid))


def digest_sql(conn: sqlite3.Connection, schema: str, table: str, cols: Sequence[str], rowid: bool, where: str = "") -> str:
    picked = (["rowid"] if rowid else []) + [quote(c) for c in cols]
    condition = f" WHERE {where}" if where else ""
    return f"SELECT {', '.join(picked)} FROM {schema}.{quote(table)}{condition} ORDER BY {_order(conn, schema, table, rowid)}"


def digest_query(conn: sqlite3.Connection, sql: str) -> Tuple[int, str]:
    hasher, count = hashlib.sha256(), 0
    for row in conn.execute(sql):
        hasher.update(repr(tuple((type(v).__name__, v) for v in row)).encode("utf-8"))
        hasher.update(b"\n")
        count += 1
    return count, hasher.hexdigest()


def legacy_tables(conn: sqlite3.Connection) -> set:
    return {r[0] for r in conn.execute(f"SELECT name FROM {LEGACY}.sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\'")}


def sequences(conn: sqlite3.Connection, schema: str, names: Sequence[str]) -> Dict[str, int]:
    marks = ",".join("?" * len(names))
    return {r[0]: int(r[1]) for r in conn.execute(f"SELECT name, seq FROM {schema}.sqlite_sequence WHERE name IN ({marks})", list(names))}


def run_script(conn: sqlite3.Connection, script: str) -> None:
    for statement in statements(script):
        conn.execute(statement)


def create_empty(conn: sqlite3.Connection) -> None:
    run_script(conn, TABLES)
    run_script(conn, TRIGGERS)
    run_script(conn, IMPORTS)
    conn.execute(f"INSERT INTO {tables.META} (k, v) VALUES ('seq', 0)")


def copy_legacy(conn: sqlite3.Connection) -> CopyResult:
    found, wanted = legacy_tables(conn), set(tables.LEGACY_NAMES.values())
    if found != wanted:
        raise WorkImportDeferred(f"huddle.db tables differ from rung 49: missing {sorted(wanted - found)}, unknown {sorted(found - wanted)}")
    run_script(conn, TABLES)
    result, plan = CopyResult(), []
    for new in tables.ALL:
        old = tables.LEGACY_NAMES[new]
        landed = tables.at_w1(new)
        cols, rowid = columns(conn, LEGACY, old), has_rowid(conn, LEGACY, old)
        if set(cols) != set(columns(conn, "main", landed)) or rowid != has_rowid(conn, "main", landed):
            raise WorkImportDeferred(f"{old} has columns {cols}, {landed} has {columns(conn, 'main', landed)}")
        picked = (["rowid"] if rowid else []) + [quote(c) for c in cols]
        conn.execute(f"INSERT INTO main.{quote(landed)} ({', '.join(picked)}) SELECT {', '.join(picked)} FROM {LEGACY}.{quote(old)}")
        plan.append((old, new, landed, cols, rowid))
    old_seq = sequences(conn, LEGACY, list(tables.LEGACY_NAMES.values()))
    renamed = {new: old_seq[old] for new, old in tables.LEGACY_NAMES.items() if old in old_seq}
    at_w1 = [tables.at_w1(name) for name in tables.ALL]
    conn.execute(f"DELETE FROM main.sqlite_sequence WHERE name IN ({','.join('?' * len(at_w1))})", at_w1)
    conn.executemany("INSERT INTO main.sqlite_sequence (name, seq) VALUES (?, ?)", sorted((tables.at_w1(n), s) for n, s in renamed.items()))
    for old, new, landed, cols, rowid in plan:
        source, copied = digest(conn, LEGACY, old, cols, rowid), digest(conn, "main", landed, cols, rowid)
        if source != copied:
            raise WorkImportDeferred(f"{new} differs from {old}: {copied[0]} rows against {source[0]}, digest {copied[1][:12]} against {source[1][:12]}")
        result.counts[new], result.digests[new] = source
    if sequences(conn, "main", at_w1) != {tables.at_w1(n): s for n, s in renamed.items()}:
        raise WorkImportDeferred("sqlite_sequence differs after the copy")
    run_script(conn, TRIGGERS)
    run_script(conn, IMPORTS)
    return result
