from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from src.core.db_reuse.deadline_loan import DeadlineLoan, discard_on_corrupt

THREE_ROWS = "SELECT 1 UNION SELECT 2 UNION SELECT 3"


def _expired_deadline(conn: sqlite3.Connection) -> None:
    conn.set_progress_handler(lambda: 1, 1)


def test_close_clears_the_deadline_handler_and_keeps_the_connection_open():
    conn = sqlite3.connect(":memory:")
    _expired_deadline(conn)
    with closing(DeadlineLoan(conn, lambda: None)) as loan:
        with pytest.raises(sqlite3.OperationalError):
            loan.execute(THREE_ROWS)
    assert len(conn.execute(THREE_ROWS).fetchall()) == 3, "the next borrower must not inherit the interrupt"


def test_with_block_clears_the_handler_and_yields_the_loan_itself():
    conn = sqlite3.connect(":memory:")
    dropped: list[int] = []
    with DeadlineLoan(conn, lambda: dropped.append(1)) as loan:
        _expired_deadline(conn)
        assert isinstance(loan, DeadlineLoan)
    assert len(conn.execute(THREE_ROWS).fetchall()) == 3
    assert dropped == []


def test_a_corrupt_file_error_drops_the_pool_entry_but_a_missing_table_does_not(tmp_path):
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a sqlite database" * 200)
    dropped: list[int] = []
    loan = DeadlineLoan(sqlite3.connect(bad), lambda: dropped.append(1))
    with pytest.raises(sqlite3.DatabaseError):
        loan.execute("SELECT * FROM t")
    assert dropped == [1]

    ok = DeadlineLoan(sqlite3.connect(":memory:"), lambda: dropped.append(2))
    with pytest.raises(sqlite3.OperationalError):
        ok.execute("SELECT * FROM missing")
    assert dropped == [1], "an OperationalError is expected, not corruption"


def test_dropping_a_loan_leaves_the_next_borrowers_handler_alone():
    conn = sqlite3.connect(":memory:")
    first = DeadlineLoan(conn, lambda: None)
    _expired_deadline(conn)
    del first
    with pytest.raises(sqlite3.OperationalError):
        conn.execute(THREE_ROWS)


def test_discard_on_corrupt_reraises_non_database_errors_untouched():
    called: list[int] = []
    with pytest.raises(KeyError):
        with discard_on_corrupt(lambda: called.append(1)):
            raise KeyError("x")
    assert called == []
