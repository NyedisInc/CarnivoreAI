
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from src.core.crate_format.canonical import text_factory
from src.cplugs.sdk.vault_sources import SourceUnavailable

BATCH_ROWS: int = 2000
_ROWID = "__rowid__"


@dataclass(frozen=True)
class RowQuery:

    db: Optional[str]
    store: str
    table: str
    where: str
    params: Tuple[Any, ...] = ()


@dataclass
class RowBatch:

    store: str
    table: str
    columns: List[str]
    decltypes: List[str]
    pk: List[str]
    rows: List[Dict[str, Any]] = field(default_factory=list)
    omitted: List[str] = field(default_factory=list)
    without_rowid: bool = False


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _open_ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True, timeout=10, isolation_level=None)
    conn.text_factory = text_factory
    return conn


def _table_shape(conn: sqlite3.Connection, table: str) -> Tuple[List[str], List[str], List[str], bool]:
    info = conn.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
    if not info:
        raise SourceUnavailable(f"table {table} is not in its database")
    columns = [str(r[1]) for r in info]
    decltypes = [str(r[2] or "") for r in info]
    pk = [str(r[1]) for r in sorted((r for r in info if r[5]), key=lambda r: r[5])]
    listed = conn.execute(f"PRAGMA table_list({_quote(table)})").fetchall()
    without_rowid = bool(listed and listed[0][4])
    return columns, decltypes, pk, without_rowid


def _table_batches(conn: sqlite3.Connection, store: str, table: str, queries: Sequence[RowQuery],
                   omit: Sequence[str]) -> Iterator[RowBatch]:
    columns, decltypes, pk, without_rowid = _table_shape(conn, table)
    omitted = [c for c in columns if c in set(omit)]
    where = " OR ".join(f"({q.where})" for q in queries)
    params: List[Any] = [p for q in queries for p in q.params]
    if without_rowid:
        sql = f"SELECT * FROM {_quote(table)} WHERE {where} ORDER BY {', '.join(_quote(c) for c in pk)}"
    else:
        sql = f"SELECT rowid AS {_ROWID}, * FROM {_quote(table)} WHERE {where} ORDER BY {_ROWID}"
    cursor = conn.execute(sql, params)
    names = [d[0] for d in cursor.description]
    keep = [(i, n) for i, n in enumerate(names) if n != _ROWID and n not in omitted]
    shape = dict(store=store, table=table, columns=[c for c in columns if c not in omitted],
                 decltypes=[t for c, t in zip(columns, decltypes) if c not in omitted], pk=pk, omitted=omitted,
                 without_rowid=without_rowid)
    sent = False
    while True:
        chunk = cursor.fetchmany(BATCH_ROWS)
        if not chunk and sent:
            return
        yield RowBatch(rows=[{n: row[i] for i, n in keep} for row in chunk], **shape)
        sent = True
        if not chunk:
            return


def _db_batches(conn: sqlite3.Connection, queries: Sequence[RowQuery],
                secret_columns: Mapping[Tuple[str, str], Sequence[str]]) -> Iterator[RowBatch]:
    by_table: Dict[str, List[RowQuery]] = {}
    for query in queries:
        by_table.setdefault(query.table, []).append(query)
    try:
        for table in sorted(by_table):
            store = by_table[table][0].store
            yield from _table_batches(conn, store, table, by_table[table], secret_columns.get((store, table), ()))
    except sqlite3.Error as exc:
        raise SourceUnavailable(f"cannot read rows of {queries[0].store}: {exc}") from exc


def _schema_version(conn: sqlite3.Connection, main: bool) -> int:
    if main:
        from src.core.db import get_schema_version

        return int(get_schema_version(conn))
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def snapshot_rows(queries: Sequence[RowQuery], secret_columns: Mapping[Tuple[str, str], Sequence[str]], *,
                  state_dir: Optional[Path] = None) -> Iterator[Tuple[str, int, Iterator[RowBatch]]]:
    from src.core.db import db_path_for

    groups: Dict[Optional[str], List[RowQuery]] = {}
    for query in queries:
        groups.setdefault(query.db, []).append(query)
    for db in sorted(groups, key=lambda d: (d is not None, d or "")):
        if db is None:
            if state_dir is None:
                from src.cplugs.sdk.transcript_files import state_dir as live_state

                state_dir = live_state()
            path = Path(db_path_for(Path(state_dir)))
        else:
            path = Path(db)
        if not path.is_file():
            continue
        try:
            conn = _open_ro(path)
        except sqlite3.Error as exc:
            raise SourceUnavailable(f"cannot open {path.name}: {exc}") from exc
        try:
            try:
                conn.execute("BEGIN")
                conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
                version = _schema_version(conn, db is None)
            except sqlite3.Error as exc:
                raise SourceUnavailable(f"cannot read {path.name}: {exc}") from exc
            yield groups[db][0].store, version, _db_batches(conn, groups[db], secret_columns)
        finally:
            conn.close()



def preflight(queries: Sequence[RowQuery], *, state_dir: Optional[Path] = None) -> Tuple[List[str], Dict[Tuple[str, str], int]]:
    from src.core.db import db_path_for

    groups: Dict[Tuple[Optional[str], str, str], List[RowQuery]] = {}
    for query in queries:
        groups.setdefault((query.db, query.store, query.table), []).append(query)
    problems: List[str] = []
    counts: Dict[Tuple[str, str], int] = {}
    for (db, store, table), group in sorted(groups.items(), key=lambda kv: (kv[0][0] or "", kv[0][1], kv[0][2])):
        if db is None:
            if state_dir is None:
                from src.cplugs.sdk.transcript_files import state_dir as live_state

                state_dir = live_state()
            path = Path(db_path_for(Path(state_dir)))
        else:
            path = Path(db)
        if not path.is_file():
            counts[(store, table)] = 0
            continue
        where = " OR ".join(f"({q.where})" for q in group)
        params = [p for q in group for p in q.params]
        try:
            conn = _open_ro(path)
            try:
                counts[(store, table)] = int(conn.execute(f"SELECT count(*) FROM {_quote(table)} WHERE {where}",
                                                          params).fetchone()[0])
            finally:
                conn.close()
        except sqlite3.Error as exc:
            problems.append(f"{store} table {table} cannot be read now ({type(exc).__name__}: {exc})")
    return problems, counts
