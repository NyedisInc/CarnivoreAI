
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.config  # noqa: F401
from fastapi import HTTPException

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_reuse.change_cache import HOT_READS
from src.core.db_reuse.kept_read import hot_read
from tests.python.perf_conn_reuse.helpers import count_connects, opens_of
from tests.python.perf_conn_reuse.test_hot_reads_round3 import run, state_dir  # noqa: F401


def make_state(root: Path, name: str, marker: str) -> Path:
    d = root / name
    d.mkdir()
    assert ensure_db_migrated(d, 4, "0.0.0").status == "ok"
    with closing(connect(db_path_for(d))) as conn, conn:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('marker', ?)", (marker,))
    return d


def marker(conn: sqlite3.Connection) -> str:
    return conn.execute("SELECT value FROM meta WHERE key='marker'").fetchone()[0]


def damage_under_the_kept_connection(monkeypatch) -> list:
    from src.core.db_reuse import datastore_pool

    forgotten: list = []
    real_lend, real_forget = datastore_pool.lend, datastore_pool.forget

    class Damaged:

        def __init__(self, conn) -> None:
            self._conn = conn

        def execute(self, sql, *args):
            if "schema_version" in sql:
                raise sqlite3.DatabaseError("file is not a database")
            return self._conn.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    monkeypatch.setattr(datastore_pool, "lend", lambda path: Damaged(real_lend(path)))
    monkeypatch.setattr(datastore_pool, "forget", lambda path: (forgotten.append(path), real_forget(path))[1])
    return forgotten


def test_a_damaged_database_is_a_503_for_a_thread_that_already_holds_a_connection(state_dir, run, monkeypatch):  # noqa: F811
    from src.api.session_records_routes import stored_record_rows

    run(stored_record_rows(SimpleNamespace()))
    forgotten = damage_under_the_kept_connection(monkeypatch)
    HOT_READS.clear()
    with pytest.raises(HTTPException) as caught:
        run(stored_record_rows(SimpleNamespace()))
    assert caught.value.status_code == 503
    assert caught.value.detail["code"] == "datastore_unavailable"
    assert forgotten == [db_path_for(state_dir)]


def test_the_recent_route_is_a_503_for_a_damaged_database(state_dir, run, monkeypatch):  # noqa: F811
    from src.api.session_recent_routes import recent_response

    app_state = SimpleNamespace(services=SimpleNamespace(probe_health=SimpleNamespace(health=SimpleNamespace(ok=True, reason=None))))
    run(recent_response(app_state))
    damage_under_the_kept_connection(monkeypatch)
    HOT_READS.clear()
    with pytest.raises(HTTPException) as caught:
        run(recent_response(app_state))
    assert caught.value.status_code == 503


def test_a_kept_connection_follows_an_opener_that_now_opens_another_file(tmp_path, monkeypatch):
    from src.api import peer_auth
    from src.config import settings

    first, second = make_state(tmp_path, "one", "ONE"), make_state(tmp_path, "two", "TWO")
    HOT_READS.clear()
    monkeypatch.setattr(settings, "state_dir_override", str(first))
    assert [hot_read(peer_auth.open_db, ("marker",), marker) for _ in range(3)] == ["ONE"] * 3
    monkeypatch.setattr(settings, "state_dir_override", str(second))
    assert [hot_read(peer_auth.open_db, ("marker",), marker) for _ in range(3)] == ["TWO"] * 3
    HOT_READS.clear()


def test_an_opener_unrelated_to_the_state_directory_is_read_correctly_and_never_kept(tmp_path):
    one, two = make_state(tmp_path, "one", "ONE"), make_state(tmp_path, "two", "TWO")
    current = {"dir": one}

    def opener() -> sqlite3.Connection:
        return connect(db_path_for(current["dir"]), create=False)

    HOT_READS.clear()
    assert [hot_read(opener, ("marker",), marker) for _ in range(3)] == ["ONE"] * 3
    current["dir"] = two
    assert [hot_read(opener, ("marker",), marker) for _ in range(3)] == ["TWO"] * 3
    HOT_READS.clear()


def test_a_failed_read_drops_the_kept_connection(state_dir, monkeypatch):  # noqa: F811
    from src.api import peer_auth

    HOT_READS.clear()
    assert hot_read(peer_auth.open_db, ("marker",), lambda conn: conn.execute("SELECT 1").fetchone()[0]) == 1

    def broken(conn: sqlite3.Connection) -> int:
        raise sqlite3.DatabaseError("file is not a database")

    with pytest.raises(sqlite3.DatabaseError):
        hot_read(peer_auth.open_db, ("broken",), broken)
    opened = count_connects(monkeypatch)
    assert hot_read(peer_auth.open_db, ("fresh",), lambda conn: conn.execute("SELECT 2").fetchone()[0]) == 2
    assert opens_of(opened, "carnivore.db") >= 1
    HOT_READS.clear()


def test_the_recent_list_does_not_keep_the_answer_of_a_failed_replaced_scan(state_dir, run, monkeypatch):  # noqa: F811
    from src.api import session_recent_routes
    from src.core import session_store
    from src.core.db_reuse import core_read

    app_state = SimpleNamespace(services=SimpleNamespace(probe_health=SimpleNamespace(health=SimpleNamespace(ok=True, reason=None))))
    failing = {"on": True}
    loads = {"n": 0}
    real_list, real_lend = session_store.list_sessions, core_read.lend_pooled_or_raise

    def counted(conn, **kwargs):
        loads["n"] += 1
        return real_list(conn, **kwargs)

    monkeypatch.setattr(session_store, "list_sessions", counted)
    monkeypatch.setattr(core_read, "lend_pooled_or_raise", lambda path: _Wrap(real_lend(path), failing))
    run(session_recent_routes.recent_response(app_state))
    run(session_recent_routes.recent_response(app_state))
    assert loads["n"] == 2
    failing["on"] = False
    run(session_recent_routes.recent_response(app_state))
    run(session_recent_routes.recent_response(app_state))
    assert loads["n"] == 3


class _Wrap:

    def __init__(self, conn, failing: dict) -> None:
        self._conn, self._failing = conn, failing

    def execute(self, sql, *args):
        if self._failing["on"] and "parent_session_id FROM sessions" in sql:
            raise sqlite3.OperationalError("scan failed")
        return self._conn.execute(sql, *args)

    def close(self) -> None:
        pass

    def __getattr__(self, name: str):
        return getattr(self._conn, name)


def test_a_symlinked_state_directory_is_still_kept(tmp_path, monkeypatch):
    from src.api import peer_auth
    from src.config import settings

    real = make_state(tmp_path, "real", "REAL")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(settings, "state_dir_override", str(link))
    HOT_READS.clear()
    for _ in range(3):
        hot_read(peer_auth.open_db, ("marker",), marker)
    opened = count_connects(monkeypatch)
    for i in range(6):
        with closing(connect(db_path_for(real))) as writer, writer:
            writer.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('marker', ?)", (f"M{i}",))
        mark = opens_of(opened, "carnivore.db")
        assert hot_read(peer_auth.open_db, ("marker",), marker) == f"M{i}"
        assert opens_of(opened, "carnivore.db") == mark
    HOT_READS.clear()
