
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from scripts.schema_ledger.ladders import LADDERS
from scripts.work.rename_sql import _rewrite_text
from src.core.schema_ledger.ledger import check_ledger, parse_ledger
from src.core.schema_ledger.snapshot import dump_schema
from src.core.work import tables
from src.core.work.importer import copy
from src.core.work.work_ladder import VERSION

SNAPSHOT = Path(__file__).resolve().parents[2] / "fixtures" / "task_manager_fresh_schema.sql"


def _renamed_snapshot() -> str:
    out, sql = [], []

    def flush() -> None:
        text = _rewrite_text("\n".join(sql))[0]
        text = re.sub(r"^CREATE (UNIQUE )?INDEX (\w+)", lambda m: f"CREATE {m.group(1) or ''}INDEX work_{m.group(2)}", text)
        out.extend(re.sub(r"^CREATE TRIGGER (\w+)", r"CREATE TRIGGER work_\1", text).splitlines())
        sql.clear()

    for line in SNAPSHOT.read_text().splitlines()[1:]:
        if line.startswith("-- "):
            flush()
            kind, name, _, table = line[3:].split(" ")
            new_table = _rewrite_text(f"FROM {table}")[0][len("FROM "):]
            out.append(f"-- {kind} {new_table if kind == 'table' else 'work_' + name} on {new_table}")
        else:
            sql.append(line)
    flush()
    return "\n".join(out)


def _blocks(dump: str) -> dict:
    out, header = {}, None
    for line in dump.strip().splitlines():
        if line.startswith("-- "):
            header = line
            out[header] = []
        else:
            out[header].append(line)
    return {k: "\n".join(v) for k, v in out.items()}


def test_w1_builds_the_legacy_schema_renamed_byte_for_byte() -> None:
    conn = sqlite3.connect(":memory:")
    copy.create_empty(conn)
    built = _blocks(dump_schema(conn).split("\n", 1)[1])
    built.pop("-- table work_imports on work_imports")
    assert built == _blocks(_renamed_snapshot())


def test_the_table_constants_are_the_tables_w1_creates() -> None:
    conn = sqlite3.connect(":memory:")
    copy.create_empty(conn)
    made = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}
    assert made == {tables.at_w1(name) for name in tables.STORED} and len(tables.ALL) == 25


def test_the_work_ledger_pins_every_rung() -> None:
    check_ledger(LADDERS["work"])
    assert len(parse_ledger(LADDERS["work"].path, "W")) == VERSION
