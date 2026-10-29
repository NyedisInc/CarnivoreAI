
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core.test_write_guard import assert_test_write_allowed  # noqa: E402
from src.core.work import tables  # noqa: E402
from src.core.work.importer import copy  # noqa: E402
from src.core.work.ladder import MIGRATIONS as LEGACY_MIGRATIONS, SCHEMA_VERSION as LEGACY_VERSION  # noqa: E402
from src.core.work.work_ladder import VERSION as WORK_VERSION, VERSION_KEY  # noqa: E402
from src.cplugs.sdk.storage import CplugSchemaError, migrate  # noqa: E402

WORK = "work"
EXPORTABLE_THROUGH = 3
DROPPED_COLUMNS = {tables.ITEMS: frozenset({"review_checks"})}
META_ONLY_WHERE = f"k != '{VERSION_KEY}'"
_SIDE_SUFFIXES = ("", "-wal", "-shm", "-journal")


class ExportRefused(Exception):
    pass


@dataclass
class ExportResult:

    path: Path
    counts: Dict[str, int] = field(default_factory=dict)
    digests: Dict[str, str] = field(default_factory=dict)


def _where(new: str) -> str:
    return META_ONLY_WHERE if new == tables.META else ""


def _check_source(conn: sqlite3.Connection) -> None:
    names = {r[0] for r in conn.execute(f"SELECT name FROM {WORK}.sqlite_master WHERE type = 'table'")}
    if tables.IMPORTS not in names or conn.execute(f"SELECT 1 FROM {WORK}.{tables.IMPORTS} WHERE id = 1").fetchone() is None:
        raise ExportRefused("carnivore.db has no work store (no import record): nothing to export")
    missing = sorted(set(tables.ALL) - names)
    if missing:
        raise ExportRefused(f"carnivore.db is missing work tables: {missing}")
    row = conn.execute(f"SELECT v FROM {WORK}.{tables.META} WHERE k = ?", (VERSION_KEY,)).fetchone()
    version = int(row[0]) if row else 0
    if version != WORK_VERSION or WORK_VERSION > EXPORTABLE_THROUGH:
        raise ExportRefused(f"the work store is at W{version}; this exporter writes rung {LEGACY_VERSION} from W1 to W{EXPORTABLE_THROUGH} only")


def _copy(conn: sqlite3.Connection) -> ExportResult:
    triggers = [r[0] for r in conn.execute("SELECT sql FROM main.sqlite_master WHERE type = 'trigger' AND sql IS NOT NULL ORDER BY name")]
    for (name,) in conn.execute("SELECT name FROM main.sqlite_master WHERE type = 'trigger' ORDER BY name").fetchall():
        conn.execute(f"DROP TRIGGER main.{copy.quote(name)}")
    plan: List[Tuple[str, str, List[str], bool]] = []
    for new in tables.ALL:
        old = tables.LEGACY_NAMES[new]
        cols, rowid = copy.columns(conn, "main", old), copy.has_rowid(conn, "main", old)
        if set(cols) != set(copy.columns(conn, WORK, new)) - DROPPED_COLUMNS.get(new, frozenset()) or rowid != copy.has_rowid(conn, WORK, new):
            raise ExportRefused(f"{new} has columns {copy.columns(conn, WORK, new)}, rung {LEGACY_VERSION}'s {old} has {cols}")
        picked = (["rowid"] if rowid else []) + [copy.quote(c) for c in cols]
        where = f" WHERE {_where(new)}" if _where(new) else ""
        conn.execute(f"DELETE FROM main.{copy.quote(old)}")
        conn.execute(f"INSERT INTO main.{copy.quote(old)} ({', '.join(picked)}) SELECT {', '.join(picked)} FROM {WORK}.{copy.quote(new)}{where}")
        plan.append((new, old, cols, rowid))
    work_seq = copy.sequences(conn, WORK, list(tables.ALL))
    legacy_seq = {tables.LEGACY_NAMES[new]: seq for new, seq in work_seq.items()}
    conn.execute("DELETE FROM main.sqlite_sequence")
    conn.executemany("INSERT INTO main.sqlite_sequence (name, seq) VALUES (?, ?)", sorted(legacy_seq.items()))
    result = ExportResult(Path())
    for new, old, cols, rowid in plan:
        source = copy.digest_query(conn, copy.digest_sql(conn, WORK, new, cols, rowid, _where(new)))
        written = copy.digest_query(conn, copy.digest_sql(conn, "main", old, cols, rowid))
        if source != written:
            raise ExportRefused(f"{old} differs from {new}: {written[0]} rows against {source[0]}")
        result.counts[old], result.digests[old] = source
    if copy.sequences(conn, "main", list(tables.LEGACY_NAMES.values())) != legacy_seq:
        raise ExportRefused("sqlite_sequence differs after the copy")
    for sql in triggers:
        conn.execute(sql)
    return result


def _fsync(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def export_to_huddle(db: Path, out: Path) -> ExportResult:
    db, out = Path(db), Path(out)
    if not db.is_file():
        raise ExportRefused(f"{db} is not a file")
    taken = [str(out) + s for s in _SIDE_SUFFIXES if Path(str(out) + s).exists()]
    if taken:
        raise ExportRefused(f"refusing to overwrite {taken}")
    if not out.parent.is_dir():
        raise ExportRefused(f"{out.parent} is not a folder")
    temp = out.with_name(f".{out.name}.partial")
    if temp.exists():
        raise ExportRefused(f"{temp} exists: a previous export was interrupted; look at it, then move it away")
    assert_test_write_allowed(temp)
    published = False
    try:
        with closing(sqlite3.connect(str(temp), isolation_level=None, timeout=30.0)) as conn:
            migrate(conn, LEGACY_MIGRATIONS, name=out.name)
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute(f"ATTACH DATABASE ? AS {WORK}", (str(db),))
            conn.execute("PRAGMA busy_timeout=30000")
            _check_source(conn)
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = _copy(conn)
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            conn.execute(f"DETACH DATABASE {WORK}")
            if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ExportRefused("the exported file failed quick_check")
            if conn.execute("PRAGMA user_version").fetchone()[0] != LEGACY_VERSION:
                raise ExportRefused(f"the exported file is not at rung {LEGACY_VERSION}")
        _fsync(temp)
        os.replace(temp, out)
        _fsync(out.parent)
        published = True
    except (sqlite3.Error, CplugSchemaError, OSError) as exc:
        raise ExportRefused(f"the export failed: {exc}") from exc
    finally:
        if not published and temp.exists():
            temp.unlink()
    result.path = out
    return result


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Export carnivore.db's work tables into a new rung-49 huddle.db (issue #1711).")
    parser.add_argument("--to-huddle", required=True, type=Path, help="the new huddle.db to write (must not exist)")
    parser.add_argument("--db", required=True, type=Path, help="the carnivore.db holding the work store (only read)")
    args = parser.parse_args(argv)
    try:
        result = export_to_huddle(args.db, args.to_huddle)
    except ExportRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"path": str(result.path), "rung": LEGACY_VERSION, "counts": result.counts}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
