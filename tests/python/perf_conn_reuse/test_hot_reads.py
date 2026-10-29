
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable, Iterator

import pytest

import src.config  # noqa: F401
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_reuse.change_cache import HOT_READS
from tests.lifecycle_helpers import add_row
from tests.python.perf_conn_reuse.helpers import count_connects, opens_of

N = 30


@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch) -> Iterator[Path]:
    d = tmp_path / "state"
    d.mkdir()
    assert ensure_db_migrated(d, 4, "0.0.0").status == "ok"
    from src.config import settings

    monkeypatch.setattr(settings, "state_dir_override", str(d))
    HOT_READS.clear()
    yield d
    HOT_READS.clear()


def write(state_dir: Path, work: Callable[[sqlite3.Connection], None]) -> None:
    with closing(connect(db_path_for(state_dir))) as conn, conn:
        work(conn)


def reads_cost(monkeypatch, read: Callable[[], object]) -> int:
    read()
    opened = count_connects(monkeypatch)
    for _ in range(N):
        read()
    return opens_of(opened, "carnivore.db")


def test_resolve_projects_opens_nothing_when_unchanged_and_sees_a_new_project(state_dir, monkeypatch):
    from src.core.project_authority import resolve_projects
    from src.core.project_writes import create_project

    assert reads_cost(monkeypatch, lambda: resolve_projects(state_dir)) == 0
    write(state_dir, lambda conn: create_project(conn, name="fresh", path=str(state_dir / "p")))
    assert [p["name"] for p in resolve_projects(state_dir).projects] == ["fresh"]
    view = resolve_projects(state_dir)
    view.projects.clear()
    view.reconcile["state"] = "edited"
    again = resolve_projects(state_dir)
    assert len(again.projects) == 1 and again.reconcile["state"] != "edited"


def test_resolve_projects_still_names_a_missing_datastore(tmp_path):
    from src.core.project_authority import MODE_DB_UNREADABLE, resolve_projects

    assert resolve_projects(tmp_path / "nothing").mode == MODE_DB_UNREADABLE


def test_project_storage_rows_open_nothing_when_unchanged_and_see_a_new_row(state_dir, monkeypatch):
    from src.api.projects_service import _storage_by_project
    from src.core.project_authority import resolve_projects
    from src.core.project_pack import store
    from src.core.project_writes import create_project

    write(state_dir, lambda conn: create_project(conn, name="packed", path=str(state_dir / "p")))
    view = resolve_projects(state_dir)
    pid = view.projects[0]["id"]
    assert reads_cost(monkeypatch, lambda: _storage_by_project(view)) == 0
    assert _storage_by_project(view) == {}
    write(state_dir, lambda conn: store.put(conn, pid, notify=False, state="unpacked"))
    assert _storage_by_project(view)[pid]["state"] == "unpacked"


def test_asleep_rows_open_nothing_when_unchanged_and_see_a_new_sleeper(state_dir, monkeypatch):
    from src.api.asleep_brief import read_asleep_rows

    db = db_path_for(state_dir)
    assert reads_cost(monkeypatch, lambda: read_asleep_rows(db)) == 0
    assert read_asleep_rows(db) == []

    def sleep_one(conn: sqlite3.Connection) -> None:
        row_id = add_row(conn, uuid="u-asleep", name="cloude_a", epoch=1000)
        conn.execute("UPDATE sessions SET lifecycle='stopped', lifecycle_source='slept_by_user' WHERE id=?", (row_id,))

    write(state_dir, sleep_one)
    rows = read_asleep_rows(db)
    assert [r["session_uuid"] for r in rows] == ["u-asleep"]
    rows[0]["session_uuid"] = "edited"
    assert read_asleep_rows(db)[0]["session_uuid"] == "u-asleep"


def test_crosstalk_session_details_open_nothing_when_unchanged_and_see_a_new_row(state_dir, monkeypatch):
    from src.core.crosstalk.directory import _session_details

    holder = {}
    write(state_dir, lambda conn: holder.update(first=add_row(conn, uuid="u-one", name="cloude_a", epoch=1)))
    first = holder["first"]
    assert reads_cost(monkeypatch, lambda: _session_details([first])) == 0
    assert _session_details([first])[first][0] == "u-one"
    write(state_dir, lambda conn: holder.update(second=add_row(conn, uuid="u-two", name="cloude_b", epoch=2)))
    second = holder["second"]
    assert _session_details([second])[second][0] == "u-two"
    assert _session_details([first, 999_999]).keys() == {first}


def test_peer_roster_opens_nothing_when_unchanged_and_sees_a_new_peer(state_dir, monkeypatch):
    from src.core.federation import peer_hosts, peer_listing
    from src.core.pack.machines.runtime import peer_infos

    def open_db() -> sqlite3.Connection:
        return connect(db_path_for(state_dir), create=False)

    keeper = open_db()
    peer_listing._PEERS_CACHE = None
    try:
        assert reads_cost(monkeypatch, lambda: peer_infos(open_db, None)) == 0
        assert peer_infos(open_db, None) == []
        write(state_dir, lambda conn: peer_hosts.upsert(conn, install_id="iid-b", label="B", grant_id="g", fid="f", initiator=True))
        assert [p.install_id for p in peer_infos(open_db, None)] == ["iid-b"]
    finally:
        keeper.close()
        peer_listing._PEERS_CACHE = None


def test_a_replaced_database_file_never_serves_the_old_files_answer(tmp_path):
    from src.core.db_reuse.change_cache import ChangeCache

    def make(path: Path, value: str) -> None:
        with closing(sqlite3.connect(path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE t (v TEXT)")
            conn.execute("INSERT INTO t VALUES (?)", (value,))
            conn.commit()

    def read(path: Path) -> str:
        with closing(sqlite3.connect(path)) as conn:
            return conn.execute("SELECT v FROM t").fetchone()[0]

    db, fresh, cache = tmp_path / "carnivore.db", tmp_path / "restore.db", ChangeCache()
    make(db, "OLD")
    assert cache.fetch(db, "k", lambda: read(db)) == "OLD"
    make(fresh, "NEW")
    for suffix in ("", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    fresh.replace(db)
    assert cache.fetch(db, "k", lambda: read(db)) == "NEW"
    cache.clear()
