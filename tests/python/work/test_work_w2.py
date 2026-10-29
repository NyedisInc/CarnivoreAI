
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from scripts.schema_ledger.ladders import LADDERS
from src.core.schema_ledger.ledger import check_ledger, parse_ledger
from src.core.schema_ledger.snapshot import dump_schema
from src.core.work import tables
from src.core.work.importer import copy, ready
from src.core.work.work_ladder import MIGRATIONS, VERSION, VERSION_KEY
from src.core.work.work_ladder.w2 import W2

HELD_ROW = "INSERT INTO work_held_tells (list_key, target, since, deadline) VALUES ('12', 'ses_a', 1.0, 2.0)"


def _w1_store() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    copy.create_empty(conn)
    conn.execute(f"INSERT INTO {tables.META} (k, v) VALUES (?, 1)", (VERSION_KEY,))
    conn.execute(HELD_ROW)
    conn.commit()
    return conn


def _table_names(conn: sqlite3.Connection) -> set:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}


def test_the_work_ladder_keeps_w2_as_the_rename() -> None:
    assert VERSION == len(MIGRATIONS) >= 2 and MIGRATIONS[1] is W2
    assert W2.strip() == "ALTER TABLE work_held_tells RENAME TO work_held_sends;"


def test_walking_w2_keeps_the_held_row_and_moves_the_name() -> None:
    conn = _w1_store()
    assert tables.at_w1(tables.HELD_SENDS) in _table_names(conn)
    copy.run_script(conn, MIGRATIONS[1])
    names = _table_names(conn)
    assert tables.HELD_SENDS in names and "work_held_tells" not in names
    assert conn.execute(f"SELECT list_key, target, since, deadline FROM {tables.HELD_SENDS}").fetchall() == [("12", "ses_a", 1.0, 2.0)]
    assert names == set(tables.STORED)


def test_the_walk_at_boot_takes_a_w1_file_to_the_current_rung_and_a_second_walk_changes_nothing(tmp_path: Path) -> None:
    db = tmp_path / "carnivore.db"
    with closing(sqlite3.connect(db)) as conn:
        copy.create_empty(conn)
        conn.execute(f"INSERT INTO {tables.META} (k, v) VALUES (?, 1)", (VERSION_KEY,))
        conn.execute(HELD_ROW)
        conn.commit()
        ready._walk(conn)
        first = dump_schema(conn)
        assert conn.execute(f"SELECT v FROM {tables.META} WHERE k = ?", (VERSION_KEY,)).fetchone()[0] == VERSION
        ready._walk(conn)
        assert dump_schema(conn) == first
        assert conn.execute(f"SELECT COUNT(*) FROM {tables.HELD_SENDS}").fetchone()[0] == 1


def test_w2_changes_only_the_one_table_name() -> None:
    before = _w1_store()
    after = _w1_store()
    copy.run_script(after, MIGRATIONS[1])
    renamed = dump_schema(before).replace("work_held_tells", "work_held_sends")
    built = dump_schema(after).replace('"work_held_sends"', "work_held_sends")
    assert sorted(built.splitlines()) == sorted(renamed.splitlines())


def test_the_legacy_name_still_maps_back_for_the_export() -> None:
    assert tables.LEGACY_NAMES[tables.HELD_SENDS] == "held_tells" and tables.at_w1(tables.ITEMS) == tables.ITEMS


def test_the_ledger_pins_w2() -> None:
    check_ledger(LADDERS["work"])
    assert [line.number for line in parse_ledger(LADDERS["work"].path, "W")] == list(range(1, VERSION + 1))


def test_a_changed_w2_would_fail_the_ledger(monkeypatch) -> None:
    import src.core.work.work_ladder as ladder
    import pytest
    from src.core.schema_ledger.errors import LedgerMismatch

    monkeypatch.setattr(ladder, "MIGRATIONS", (ladder.MIGRATIONS[0], W2.replace("work_held_sends", "work_held_sendz")))
    with pytest.raises(LedgerMismatch):
        check_ledger(LADDERS["work"])
