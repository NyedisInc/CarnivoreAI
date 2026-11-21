
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Sequence, Tuple

import structlog

logger = structlog.get_logger()

SchemaObject = Tuple[str, str]
MasterRow = Tuple[str, str, str, str]

_canonical_lock = threading.Lock()
_canonical_cache: Dict[Tuple[str, ...], "Canonical"] = {}


class ReconcileRefused(Exception):
    pass


@dataclass(frozen=True)
class Canonical:

    rung_objects: Tuple[FrozenSet[SchemaObject], ...]
    master: FrozenSet[MasterRow]
    columns: Dict[str, List[str]]
    table_sql: Dict[str, str]
    dependents: Dict[str, List[str]]


@dataclass
class Plan:

    run: List[int] = field(default_factory=list)
    skipped: List[int] = field(default_factory=list)
    out_of_turn: List[int] = field(default_factory=list)

    @property
    def diverged(self) -> bool:
        return bool(self.skipped or self.out_of_turn)


def statements(script: str) -> List[str]:
    out: List[str] = []
    buffer = ""
    for part in script.split(";"):
        buffer += part + ";"
        if sqlite3.complete_statement(buffer):
            if buffer.strip(" \t\r\n;"):
                out.append(buffer.strip())
            buffer = ""
    if buffer.strip(" \t\r\n;"):
        raise ReconcileRefused(f"incomplete SQL statement in a rung: {buffer.strip()[:80]!r}")
    return out


def objects(conn: sqlite3.Connection) -> FrozenSet[SchemaObject]:
    found = set()
    rows = conn.execute("SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
    for kind, name in rows:
        found.add((kind, name))
        if kind == "table":
            found.update(("column", f"{name}.{col[1]}") for col in conn.execute(f'PRAGMA table_info("{name}")'))
    return frozenset(found)


def master_rows(conn: sqlite3.Connection) -> FrozenSet[MasterRow]:
    rows = conn.execute(
        "SELECT type, name, tbl_name, COALESCE(sql, '') FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
    return frozenset((r[0], r[1], r[2], " ".join(r[3].split())) for r in rows)


def canonical(migrations: Sequence[str]) -> Canonical:
    key = tuple(migrations)
    with _canonical_lock:
        cached = _canonical_cache.get(key)
        if cached is not None:
            return cached
        conn = sqlite3.connect(":memory:")
        try:
            before = objects(conn)
            added: List[FrozenSet[SchemaObject]] = []
            for script in migrations:
                conn.executescript(f"BEGIN; {script} COMMIT;")
                after = objects(conn)
                added.append(after - before)
                before = after
            final = before
            columns = {name: [c[1] for c in conn.execute(f'PRAGMA table_info("{name}")')]
                       for (kind, name) in final if kind == "table"}
            table_sql: Dict[str, str] = {}
            dependents: Dict[str, List[str]] = {}
            for kind, name, table, sql in conn.execute(
                    "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY rowid"):
                if kind == "table":
                    table_sql[name] = sql
                elif sql:
                    dependents.setdefault(table, []).append(sql)
            built = Canonical(
                rung_objects=tuple(frozenset(objs & final) for objs in added),
                master=master_rows(conn), columns=columns, table_sql=table_sql, dependents=dependents)
        finally:
            conn.close()
        _canonical_cache[key] = built
        return built


def plan(conn: sqlite3.Connection, migrations: Sequence[str], version: int) -> Plan:
    shape = canonical(migrations)
    present = objects(conn)
    out = Plan()
    for index, rung in enumerate(shape.rung_objects):
        have = rung & present
        if have and have != rung:
            missing = sorted(name for _, name in rung - present)
            raise ReconcileRefused(f"rung {index + 1} is partly present (missing {', '.join(missing)})")
        claimed = index < version
        if claimed and rung and not have:
            out.run.append(index)
            out.out_of_turn.append(index)
        elif not claimed and rung and have == rung:
            out.skipped.append(index)
        elif not claimed:
            out.run.append(index)
    return out


def _rebuild(conn: sqlite3.Connection, table: str, shape: Canonical) -> None:
    seq = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)).fetchone() \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'sqlite_sequence'").fetchone() else None
    old = f"{table}__reconcile_old"
    cols = ", ".join(f'"{c}"' for c in shape.columns[table])
    conn.execute(f'ALTER TABLE "{table}" RENAME TO "{old}"')
    conn.execute(shape.table_sql[table])
    conn.execute(f'INSERT INTO "{table}" ({cols}) SELECT {cols} FROM "{old}"')
    conn.execute(f'DROP TABLE "{old}"')
    for sql in shape.dependents.get(table, []):
        conn.execute(sql)
    if seq is not None:
        conn.execute("UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = ?", (seq[0], table))
        if conn.execute("SELECT changes()").fetchone()[0] == 0:
            conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (table, seq[0]))


def apply(conn: sqlite3.Connection, migrations: Sequence[str], decided: Plan, *, name: str) -> None:
    shape = canonical(migrations)
    fk_on = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    legacy = conn.execute("PRAGMA legacy_alter_table").fetchone()[0]
    isolation = conn.isolation_level
    conn.isolation_level = None
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    rebuilt: List[str] = []
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for index in decided.run:
                for statement in statements(migrations[index]):
                    conn.execute(statement)
            for table, order in shape.columns.items():
                have = [c[1] for c in conn.execute(f'PRAGMA table_info("{table}")')]
                if have != order and sorted(have) == sorted(order):
                    _rebuild(conn, table, shape)
                    rebuilt.append(table)
            conn.execute(f"PRAGMA user_version = {len(migrations)}")
            result = master_rows(conn)
            if result != shape.master:
                extra = sorted(r[1] for r in result - shape.master)
                absent = sorted(r[1] for r in shape.master - result)
                raise ReconcileRefused(f"reconciled schema is not canonical (differs: {extra}; expected: {absent})")
            broken = conn.execute("PRAGMA foreign_key_check").fetchall()
            if broken:
                raise ReconcileRefused(f"foreign key check failed on {len(broken)} row(s)")
        except (ReconcileRefused, sqlite3.Error):
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
    finally:
        conn.execute(f"PRAGMA legacy_alter_table = {int(legacy)}")
        conn.execute(f"PRAGMA foreign_keys = {int(fk_on)}")
        conn.isolation_level = isolation
    logger.warning("cplug_schema_reconciled", db=name, ran=[i + 1 for i in decided.run],
                   out_of_turn=[i + 1 for i in decided.out_of_turn], skipped=[i + 1 for i in decided.skipped],
                   rebuilt=rebuilt, to=len(migrations))
