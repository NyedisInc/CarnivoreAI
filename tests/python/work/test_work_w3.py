
from __future__ import annotations

import sqlite3

from scripts.schema_ledger.ladders import LADDERS
from src.core.schema_ledger.ledger import check_ledger
from src.core.work import tables
from src.core.work.importer import copy
from src.core.work.work_ladder import MIGRATIONS, VERSION, VERSION_KEY
from src.core.work.work_ladder.w3 import W3
from tests.python.work.test_work_w2 import _table_names


def _at_w2() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    copy.create_empty(conn)
    conn.execute(f"INSERT INTO {tables.META} (k, v) VALUES (?, 2)", (VERSION_KEY,))
    conn.execute("INSERT INTO work_items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, seq) "
                 "VALUES ('all', 'old row', 0, 'joe', 'open', 1, 1, 1, 1)")
    conn.commit()
    return conn


def test_w3_is_the_third_rung_and_one_column() -> None:
    assert VERSION == len(MIGRATIONS) == 3 and MIGRATIONS[2] is W3
    assert W3.strip() == "ALTER TABLE work_items ADD COLUMN review_checks TEXT;"


def test_walking_w3_keeps_every_row_and_reads_null() -> None:
    conn = _at_w2()
    before = _table_names(conn)
    copy.run_script(conn, MIGRATIONS[2])
    assert _table_names(conn) == before
    assert "review_checks" in copy.columns(conn, "main", tables.ITEMS)
    assert conn.execute("SELECT text, review_checks FROM work_items").fetchall() == [("old row", None)]


def test_the_ledger_pins_w3() -> None:
    check_ledger(LADDERS["work"])
