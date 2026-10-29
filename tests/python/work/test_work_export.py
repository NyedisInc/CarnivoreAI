
from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from scripts.work import work_export
from src.core.work import tables
from src.core.work.importer import copy, ready
from src.core.work.ladder import SCHEMA_VERSION as LEGACY_VERSION
from src.core.work.storage import storage_for
from src.cplugs.huddle.store import TaskManagerStore
from src.cplugs.sdk.storage import CplugStorage
from tests.python.work.test_work_import import _legacy


@pytest.fixture
def states(tmp_path: Path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    yield a, b
    for state in (a, b):
        ready.forget(state / "carnivore.db")


def _digests(db: Path, names, schema_of=lambda name: name) -> dict:
    with closing(sqlite3.connect(db)) as conn:
        out = {}
        for name in names:
            table = schema_of(name)
            cols, rowid = copy.columns(conn, "main", table), copy.has_rowid(conn, "main", table)
            cols = [c for c in cols if c not in work_export.DROPPED_COLUMNS.get(name, frozenset())]
            out[name] = copy.digest(conn, "main", table, cols, rowid)
        return out


def _imported_then_written(state: Path) -> Path:
    _legacy(state)
    storage = storage_for(state)
    storage.ensure_ready()
    store = TaskManagerStore(storage, notify=lambda key: None)
    item = store.add("7", "written after the import", actor="claude")["id"]
    store.post(item, "a reply after the import", actor="claude")
    return storage.db_path


def test_an_export_holds_every_row_written_after_the_import_and_imports_back_identically(states, tmp_path: Path) -> None:
    a, b = states
    source = _imported_then_written(a)
    before = _digests(source, tables.ALL)
    out = tmp_path / "out" / "huddle.db"
    out.parent.mkdir()
    result = work_export.export_to_huddle(source, out)
    assert _digests(source, tables.ALL) == before
    with closing(sqlite3.connect(out)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == LEGACY_VERSION
        assert conn.execute("SELECT text FROM items ORDER BY id DESC LIMIT 1").fetchone()[0] == "written after the import"
        assert conn.execute("SELECT k FROM meta ORDER BY k").fetchall() == [("seq",)]
    exported = _digests(out, tables.ALL, tables.LEGACY_NAMES.__getitem__)
    for new in tables.ALL:
        if new != tables.META:
            assert exported[new] == before[new], new
        assert result.digests[tables.LEGACY_NAMES[new]] == exported[new][1]
    folder = b / "cplugs" / "huddle"
    folder.mkdir(parents=True)
    shutil.copy2(out, folder / "huddle.db")
    storage_for(b).ensure_ready()
    assert _digests(storage_for(b).db_path, tables.ALL) == before
    with closing(sqlite3.connect(source)) as one, closing(sqlite3.connect(storage_for(b).db_path)) as two:
        assert copy.sequences(one, "main", list(tables.ALL)) == copy.sequences(two, "main", list(tables.ALL))


def test_an_older_build_opens_the_export_with_no_walk_and_its_triggers_work(states, tmp_path: Path) -> None:
    a, _ = states
    out = tmp_path / "huddle.db"
    work_export.export_to_huddle(_imported_then_written(a), out)
    fresh = tmp_path / "fresh"
    with closing(CplugStorage(fresh, ready.legacy_spec()).connect(True)) as conn:
        wanted = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
    old_build = tmp_path / "old"
    old_build.mkdir()
    shutil.copy2(out, old_build / "huddle.db")
    with closing(CplugStorage(old_build, ready.legacy_spec()).connect(True)) as conn:
        assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")} == wanted
        conn.execute("UPDATE items SET claude_working = 1, claude_working_by = 's5' WHERE id = 2")
        conn.execute("UPDATE items SET state = 'review' WHERE id = 2")
        assert tuple(conn.execute("SELECT claude_working, owner_session_key FROM items WHERE id = 2").fetchone()) == (0, "s5")
    assert not list(old_build.glob("huddle.db.pre-*"))


def test_an_existing_output_is_refused_and_left_alone(states, tmp_path: Path) -> None:
    a, _ = states
    source = _imported_then_written(a)
    out = tmp_path / "huddle.db"
    out.write_bytes(b"keep me")
    assert work_export.main(["--to-huddle", str(out), "--db", str(source)]) == 1
    assert out.read_bytes() == b"keep me"
    assert not list(tmp_path.glob(".huddle.db.partial"))


def test_a_carnivore_db_with_no_work_store_is_refused_and_nothing_is_published(tmp_path: Path) -> None:
    db = tmp_path / "carnivore.db"
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v)")
    with pytest.raises(work_export.ExportRefused, match="no work store"):
        work_export.export_to_huddle(db, tmp_path / "huddle.db")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["carnivore.db"]


def test_a_column_the_legacy_rung_cannot_hold_is_refused(states, tmp_path: Path) -> None:
    a, _ = states
    source = _imported_then_written(a)
    with closing(sqlite3.connect(source)) as conn:
        conn.execute(f"ALTER TABLE {tables.ITEMS} ADD COLUMN later TEXT")
        conn.commit()
    with pytest.raises(work_export.ExportRefused, match="work_items has columns"):
        work_export.export_to_huddle(source, tmp_path / "huddle.db")
    assert not (tmp_path / "huddle.db").exists() and not (tmp_path / ".huddle.db.partial").exists()
