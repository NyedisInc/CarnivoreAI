
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

from src.core.inventory import claims as K
from src.core.inventory.claims import ClaimBook

_IDENTITY = re.compile(r"(session|conversation|project|tmux|agent_id|company|companion|thread|list_key|cwd|folder|uuid|(^|_)uid$"
                       r"|(^|_)(path|root|dir|directory)$|_id$|_ref$|_key$)")
_NOT_IDENTITY = re.compile(r"((?<!tmux)_name|_at|_by|_state|_scheme|_attribution|_source|_count|_title|_epoch|_kind|_family|_type|(dedupe|native|name|title|detail|seed|doc|identity)_key)$")


@dataclass(frozen=True)
class TableInfo:

    name: str
    columns: Tuple[str, ...]
    virtual: bool


def identity_columns(columns: Tuple[str, ...]) -> List[str]:
    return [c for c in columns if _IDENTITY.search(c) and not _NOT_IDENTITY.search(c)]


def read_tables(conn: sqlite3.Connection) -> Dict[str, TableInfo]:
    out: Dict[str, TableInfo] = {}
    rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall()
    for name, sql in rows:
        columns = tuple(r[1] for r in conn.execute(f"PRAGMA table_info('{name}')"))
        out[str(name)] = TableInfo(str(name), columns, "VIRTUAL" in (sql or "").upper())
    return out


def _shadows(tables: Dict[str, TableInfo]) -> Set[str]:
    virtual = [t.name for t in tables.values() if t.virtual]
    return {t for t in tables for v in virtual if t.startswith(v + "_")}


def _check_claimed(book: ClaimBook, store: str, info: TableInfo) -> List[str]:
    claimed = book.claims_for(store, info.name)
    named: Set[str] = set()
    problems: List[str] = []
    for claim in claimed:
        for field in (*claim.keys, *claim.paths, *claim.ignored, *claim.secret):
            column = field.split("#", 1)[0]
            named.add(column)
            if column not in info.columns:
                problems.append(f"{store}.{info.name}: the claim names {column!r}, which is not a column")
        if claim.covered_by and not book.claims_for(store, claim.covered_by):
            problems.append(f"{store}.{info.name}: covered_by {claim.covered_by!r} is not a claimed table")
    missing = [c for c in identity_columns(info.columns) if c not in named]
    if missing:
        problems.append(f"{store}.{info.name}: identity-looking column(s) {missing} are neither keys, paths nor ignored in the claim")
    return problems


def _check_excluded(excluded: K.Exclusion, info: TableInfo) -> List[str]:
    if excluded.kind == K.SHADOW:
        return []
    for column in excluded.ignored:
        if column not in info.columns:
            return [f"{excluded.store}.{info.name}: the exclusion ignores {column!r}, which is not a column"]
    found = [c for c in identity_columns(info.columns) if c not in excluded.ignored]
    if not found:
        return []
    return [f"{excluded.store}.{info.name}: excluded as {excluded.kind} but has identity-looking column(s) {found}; "
            "claim the table, or list them in the exclusion's ignored with the reason"]


def audit(book: ClaimBook, store: str, conn: sqlite3.Connection) -> List[str]:
    tables = read_tables(conn)
    shadows = _shadows(tables)
    problems: List[str] = []
    for name, info in sorted(tables.items()):
        claimed, excluded = book.claims_for(store, name), book.exclusion_for(store, name)
        if claimed and excluded:
            problems.append(f"{store}.{name}: both claimed and excluded")
        elif claimed:
            problems += _check_claimed(book, store, info)
        elif excluded:
            problems += _check_excluded(excluded, info)
        elif name not in shadows:
            problems.append(f"{store}.{name}: neither claimed nor excluded (identity-looking columns: {identity_columns(info.columns)})")
    registered = ({c.table for c in book.claims if c.store == store and not c.absent_ok}
                  | {e.table for e in book.exclusions if e.store == store and not e.absent_ok})
    problems += [f"{store}.{t}: registered but not in the schema" for t in sorted(registered - set(tables))]
    return problems
