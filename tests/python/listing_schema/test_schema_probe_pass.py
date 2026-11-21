
from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.core.db import column_exists, connect, table_exists
from src.core.hosts.table_columns import schema_pass, table_columns
from src.core.listing_prefetch import build_listing_prefetch
from src.core.session_label import label_for_name
from src.core.session_store import identity_for_live_name
from tests.lifecycle_helpers import SOCKET, add_row, conn  # noqa: F401

_NOW = "2026-11-18T00:00:00Z"


def _project(conn: sqlite3.Connection, root: str, name: str) -> int:
    cur = conn.execute(
        "INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at) "
        "VALUES (?, ?, ?, 'test', ?, ?)",
        (root, root, name, _NOW, _NOW),
    )
    return int(cur.lastrowid)


def _seed(conn: sqlite3.Connection, count: int) -> List[str]:
    p1, p2 = _project(conn, "/tmp/p1", "one"), _project(conn, "/tmp/p2", "two")
    names: List[str] = []
    for i in range(count):
        name = f"cloude_n{i}"
        add_row(conn, uuid=f"u{i}", name=name, epoch=1000 + i)
        conn.execute(
            "UPDATE sessions SET project_id = ?, title = ? WHERE session_uuid = ?",
            (p1 if i % 2 else p2, f"label {i}" if i % 3 == 0 else None, f"u{i}"),
        )
        names.append(name)
    add_row(conn, uuid="ua", name="adopted-x", epoch=5000, origin="adopted")
    names.append("adopted-x")
    names.append("cloude_unknown")
    return names


def _answers(conn: sqlite3.Connection, names: List[str]) -> Dict[str, Tuple[Optional[str], Optional[dict]]]:
    return {
        n: (
            label_for_name(conn, socket=SOCKET, name=n),
            identity_for_live_name(conn, socket=SOCKET, name=n),
        )
        for n in names
    }


def _schema_statements(conn: sqlite3.Connection, run) -> int:
    seen: List[str] = []
    conn.set_trace_callback(seen.append)
    try:
        run()
    finally:
        conn.set_trace_callback(None)
    return sum(1 for s in seen if "PRAGMA" in s.upper() or "sqlite_master" in s)


def test_answers_in_a_pass_equal_the_uncached_answers(conn):
    names = _seed(conn, 8)
    plain = _answers(conn, names)
    with schema_pass():
        passed = _answers(conn, names)
    assert passed == plain
    assert plain["cloude_unknown"] == (None, None)
    assert plain["cloude_n0"][0] == "label 0" and plain["cloude_n0"][1]["project_name"] == "two"
    assert plain["cloude_n1"][1]["project_name"] == "one"
    assert plain["adopted-x"][1] is not None


def test_n_names_cause_one_schema_read(conn):
    names = _seed(conn, 30)
    outside = _schema_statements(conn, lambda: _answers(conn, names))
    with schema_pass():
        few = _schema_statements(conn, lambda: _answers(conn, names[:2]))
    with schema_pass():
        many = _schema_statements(conn, lambda: _answers(conn, names))
    assert outside > len(names)
    assert many == few
    assert many <= 12


def test_build_listing_prefetch_runs_its_batch_in_a_pass(conn):
    names = _seed(conn, 30)
    batch = lambda unique: {n: (label_for_name(conn, socket=SOCKET, name=n),
                                identity_for_live_name(conn, socket=SOCKET, name=n))
                            for n in unique}
    holder: Dict[str, object] = {}

    def run() -> None:
        holder["p"] = build_listing_prefetch(
            names=names, label_for_name=lambda n: None, identity_for_live_name=lambda n: None,
            label_identity_for_names=batch)

    assert _schema_statements(conn, run) <= 12
    got = {n: (holder["p"].by_name[n].label, holder["p"].by_name[n].identity) for n in names}
    assert got == _answers(conn, names)


def test_a_table_created_after_an_absent_answer_is_seen_on_the_next_pass(conn, tmp_path):
    other = connect(Path(conn.execute("PRAGMA database_list").fetchone()[2]))
    with closing(other):
        with schema_pass():
            assert table_exists(conn, "zz_late") is False
            assert table_columns(conn, "zz_late") == frozenset()
            other.execute("CREATE TABLE zz_late (a TEXT)")
        with schema_pass():
            assert table_exists(conn, "zz_late") is True
            assert table_columns(conn, "zz_late") == frozenset({"a"})


def test_a_column_added_later_is_seen_on_the_next_pass(conn):
    other = connect(Path(conn.execute("PRAGMA database_list").fetchone()[2]))
    with closing(other):
        other.execute("CREATE TABLE zz_cols (a TEXT)")
        with schema_pass():
            assert column_exists(conn, "zz_cols", "b") is False
            other.execute("ALTER TABLE zz_cols ADD COLUMN b TEXT")
        with schema_pass():
            assert column_exists(conn, "zz_cols", "b") is True


def test_two_databases_do_not_share_answers(conn, tmp_path):
    second = connect(tmp_path / "second.db")
    with closing(second):
        second.execute("CREATE TABLE zz_only (x TEXT)")
        conn.execute("CREATE TABLE zz_only (y TEXT)")
        with schema_pass():
            assert table_columns(second, "zz_only") == frozenset({"x"})
            assert table_columns(conn, "zz_only") == frozenset({"y"})
            assert table_exists(second, "sessions") is False
            assert table_exists(conn, "sessions") is True


def test_a_connection_inside_a_transaction_is_never_memoized(conn):
    with schema_pass():
        conn.execute("BEGIN")
        conn.execute("CREATE TABLE zz_tx (a TEXT)")
        assert table_exists(conn, "zz_tx") is True
        assert table_columns(conn, "zz_tx") == frozenset({"a"})
        conn.execute("ROLLBACK")
        assert table_exists(conn, "zz_tx") is False
        assert table_columns(conn, "zz_tx") == frozenset()


def test_a_pass_is_private_to_its_thread_and_ends_with_its_block(conn):
    names = _seed(conn, 6)
    counts: List[int] = []
    path = Path(conn.execute("PRAGMA database_list").fetchone()[2])

    def other_thread() -> None:
        own = connect(path)
        with closing(own):
            counts.append(_schema_statements(own, lambda: _answers(own, names)))

    with schema_pass():
        t = threading.Thread(target=other_thread)
        t.start()
        t.join()
        with schema_pass():
            assert _schema_statements(conn, lambda: table_exists(conn, "sessions")) <= 1
    assert counts[0] > len(names)
    assert _schema_statements(conn, lambda: _answers(conn, names)) > len(names)
