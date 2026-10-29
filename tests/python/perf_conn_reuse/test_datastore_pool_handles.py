
from __future__ import annotations

import gc
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

import pytest

import src.config  # noqa: F401

from src.api import peer_auth
from src.core.db import connect, db_path_for
from src.core.db_reuse import datastore_pool
from src.core.db_reuse.thread_connections import ThreadConnections
from tests.python.perf_conn_reuse.helpers import count_connects, opens_of
from tests.python.perf_conn_reuse.test_hot_reads_round3 import state_dir  # noqa: F401


@pytest.fixture(autouse=True)
def fresh_pool():
    datastore_pool._POOL.close_this_thread()
    yield
    datastore_pool._POOL.close_this_thread()


def test_hundred_peer_auth_reads_open_one_connection(state_dir, monkeypatch):  # noqa: F811
    opened = count_connects(monkeypatch)
    for _ in range(100):
        with closing(peer_auth.open_db()) as conn:
            assert conn.execute("SELECT 1").fetchone()[0] == 1
    assert opens_of(opened, "carnivore.db") == 1


def test_leaked_transaction_is_rolled_back_on_hand_back(state_dir):  # noqa: F811
    path = db_path_for(state_dir)
    other = connect(path)
    other.execute("PRAGMA busy_timeout=100")
    try:
        lent = datastore_pool.lend(path)
        lent.execute("BEGIN IMMEDIATE")
        lent.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('leak', 'x')")
        lent.close()
        assert lent.in_transaction is False
        other.execute("BEGIN IMMEDIATE")
        assert other.execute("SELECT 1 FROM meta WHERE key='leak'").fetchone() is None
        other.rollback()

        dropped = datastore_pool.lend(path)
        dropped.execute("BEGIN IMMEDIATE")
        dropped.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('leak', 'y')")
        del dropped
        gc.collect()
        other.execute("BEGIN IMMEDIATE")
        assert other.execute("SELECT 1 FROM meta WHERE key='leak'").fetchone() is None
        other.rollback()
    finally:
        other.close()


def _lend_and_exit(path: Path, seen: list) -> None:
    lent = datastore_pool.lend(path)
    lent.execute("SELECT 1").fetchone()
    seen.append(lent._conn)
    lent.close()


def _is_closed(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("SELECT 1")
    except sqlite3.ProgrammingError as exc:
        return "closed" in str(exc)
    return False


def test_exited_thread_leaves_no_open_connection(state_dir, tmp_path, monkeypatch):  # noqa: F811
    real = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: real(*a, **{**k, "check_same_thread": False}))
    gc.disable()
    try:
        seen: list = []
        thread = threading.Thread(target=_lend_and_exit, args=(db_path_for(state_dir), seen))
        thread.start()
        thread.join()
        assert _is_closed(seen[0])

        pools = [ThreadConnections(lambda p: sqlite3.connect(p)) for _ in range(3)]
        kept: list = []

        def touch() -> None:
            for index, pool in enumerate(pools):
                conn = pool.get(tmp_path / f"side{index}.db")
                conn.execute("CREATE TABLE IF NOT EXISTS t (x)")
                kept.append(conn)

        workers = [threading.Thread(target=touch) for _ in range(3)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        assert len(kept) == 9
        assert all(_is_closed(conn) for conn in kept)
    finally:
        gc.enable()


def test_nested_borrow_keeps_outer_transaction(state_dir):  # noqa: F811
    outer = peer_auth.open_db()
    outer.execute("BEGIN IMMEDIATE")
    with closing(peer_auth.open_db()) as inner:
        inner.execute("SELECT 1").fetchone()
    assert outer.in_transaction is True
    outer.close()
    assert outer.in_transaction is False
    outer.close()


def test_connect_keeps_synchronous_full(state_dir):  # noqa: F811
    with closing(connect(db_path_for(state_dir))) as conn:
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2


def test_forget_under_an_outer_loan_does_not_break_it(state_dir):  # noqa: F811
    path = db_path_for(state_dir)
    outer = datastore_pool.lend(path)
    real = datastore_pool._POOL.held(path)
    datastore_pool.forget(path)
    datastore_pool.forget_if_broken(path, sqlite3.DatabaseError("malformed"))
    assert outer.execute("SELECT 1").fetchone()[0] == 1
    outer.close()
    with pytest.raises(sqlite3.ProgrammingError):
        real.execute("SELECT 1")
    with closing(datastore_pool.lend(path)) as again:
        assert again.execute("SELECT 1").fetchone()[0] == 1


def test_forget_if_broken_ignores_a_busy_lock(state_dir):  # noqa: F811
    path = db_path_for(state_dir)
    with closing(datastore_pool.lend(path)):
        pass
    kept = datastore_pool._POOL.held(path)
    datastore_pool.forget_if_broken(path, sqlite3.OperationalError("database is locked"))
    assert datastore_pool._POOL.held(path) is kept


def test_token_dropped_unclosed_does_not_pin_the_next_borrow(state_dir):  # noqa: F811
    path = db_path_for(state_dir)
    other = connect(path)
    other.execute("PRAGMA busy_timeout=100")
    try:
        leaked = datastore_pool.lend(path)
        leaked.execute("BEGIN IMMEDIATE")
        leaked._release = None
        del leaked
        gc.collect()
        with closing(datastore_pool.lend(path)) as nxt:
            assert nxt.in_transaction is False
            other.execute("BEGIN IMMEDIATE")
            other.rollback()
    finally:
        other.close()


def test_kept_read_reuses_a_non_pool_opener(tmp_path, monkeypatch, state_dir):  # noqa: F811
    from src.core.db_reuse import kept_read

    opened = []

    def own_opener():
        opened.append(1)
        return connect(db_path_for(state_dir))

    for _ in range(5):
        with kept_read.kept_connection(own_opener) as conn:
            conn.execute("SELECT 1").fetchone()
    assert len(opened) == 1
    kept_read._pool_for(own_opener).close_this_thread()


def test_pool_dropped_on_another_thread_closes_on_the_owner(tmp_path, caplog):
    gc.disable()
    try:
        kept: list = []
        pool = ThreadConnections(lambda p: sqlite3.connect(p, check_same_thread=False))
        gate, done = threading.Event(), threading.Event()

        def owner() -> None:
            conn = pool.get(tmp_path / "x.db")
            conn.execute("CREATE TABLE IF NOT EXISTS t (x)")
            kept.append(conn)
            done.set()
            gate.wait(5)

        worker = threading.Thread(target=owner)
        worker.start()
        done.wait(5)
        del pool
        gc.collect()
        assert not _is_closed(kept[0])
        gate.set()
        worker.join()
        assert _is_closed(kept[0])
    finally:
        gc.enable()
