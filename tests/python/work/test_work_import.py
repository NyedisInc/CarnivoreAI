
from __future__ import annotations

import hashlib
import json
import time
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from src.core.work import tables
from src.core.work.importer import copy, ready
from src.core.work.importer.errors import WorkImportDeferred
from src.core.work.ladder import SCHEMA_VERSION as LEGACY_VERSION
from src.core.work.storage import WorkStorage, storage_for
from src.cplugs.sdk.storage import CplugStorage


@pytest.fixture
def state(tmp_path: Path) -> Path:
    yield tmp_path
    ready.forget(tmp_path / "carnivore.db")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _legacy(state: Path) -> Path:
    folder = state / "cplugs" / "huddle"
    with closing(CplugStorage(folder, ready.legacy_spec(), state).connect(True)) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for n in range(1, 6):
            conn.execute("INSERT INTO items (id, list_key, text, position, created_by, state, created_at, updated_at, created_seq, seq, "
                         "owner_session_key, claude_working, claude_working_by) VALUES (?, '7', ?, ?, 'joe', ?, 1.5, 2.25, ?, ?, ?, ?, ?)",
                         (n * 2, f"task {n}", n, "done" if n == 1 else "open", n, n, "s1" if n == 1 else "", 1 if n == 2 else 0,
                          "s9" if n == 2 else ""))
        conn.execute("DELETE FROM items WHERE id = 10")
        conn.execute("INSERT INTO messages (item_id, author, kind, text, created_at, seq) VALUES (2, 'claude', 'info', 'é ok', 3.0, 6)")
        conn.execute("INSERT INTO messages (item_id, author, kind, text, created_at, seq) VALUES (99, 'claude', 'info', 'orphan', 3.0, 7)")
        conn.execute("INSERT INTO reads (session_id, list_key, cursor) VALUES ('s1', '7', 6)")
        conn.execute("UPDATE meta SET v = 7 WHERE k = 'seq'")
        conn.commit()
    return folder / "huddle.db"


def _counts(conn: sqlite3.Connection, names) -> dict:
    return {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in names}


def test_a_fresh_install_builds_w1_empty_and_sets_the_switch(state: Path) -> None:
    storage = storage_for(state)
    storage.ensure_ready()
    with closing(storage.connect(False)) as conn:
        assert _counts(conn, tables.ALL)[tables.ITEMS] == 0
        assert tuple(conn.execute("SELECT kind, store_home FROM work_imports").fetchone()) == ("fresh", "carnivore.db")
        assert conn.execute("SELECT v FROM work_meta WHERE k = 'seq'").fetchone()[0] == 0
    assert not (state / "cplugs" / "huddle" / "huddle.db").exists()


def test_an_import_copies_every_row_with_its_id_and_leaves_huddle_db_untouched(state: Path) -> None:
    legacy = _legacy(state)
    with closing(sqlite3.connect(legacy)) as src:
        before = {new: src.execute(f"SELECT COUNT(*) FROM {old}").fetchone()[0] for new, old in tables.LEGACY_NAMES.items()}
        rows = src.execute("SELECT * FROM items ORDER BY id").fetchall()
    sha = _sha(legacy)
    storage_for(state).ensure_ready()
    assert _sha(legacy) == sha
    with closing(storage_for(state).connect(True)) as conn:
        assert _counts(conn, tables.ALL) == {**before, tables.META: before[tables.META] + 1}
        assert [tuple(r)[:len(rows[0])] for r in conn.execute("SELECT * FROM work_items ORDER BY id")] == [tuple(r) for r in rows]
        record = tuple(conn.execute("SELECT kind, source_version, source_sha256, counts FROM work_imports").fetchone())
        assert record[:3] == ("import", LEGACY_VERSION, sha) and json.loads(record[3]) == before
        conn.execute("INSERT INTO work_items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, seq) "
                     "VALUES ('7', 'next', 9, 'joe', 'open', 1, 1, 8, 8)")
        assert conn.execute("SELECT MAX(id) FROM work_items").fetchone()[0] == 11
        assert conn.execute("SELECT text FROM work_messages WHERE item_id = 2").fetchone()[0] == "é ok"
    folder = legacy.parent
    assert json.loads((folder / "IMPORTED.json").read_text())["source_sha256"] == sha
    assert len(list(folder.glob("huddle.db.pre-work-import-*"))) == 1
    assert not legacy.stat().st_mode & 0o222


def test_a_verification_failure_defers_and_rolls_everything_back(state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    legacy = _legacy(state)
    sha, real = _sha(legacy), copy.digest

    def lying(conn, schema, table, cols, rowid):
        count, digest = real(conn, schema, table, cols, rowid)
        return (count, "0" * 64) if schema == "main" and table == tables.MESSAGES else (count, digest)

    monkeypatch.setattr(copy, "digest", lying)
    with pytest.raises(WorkImportDeferred, match="work_messages differs"):
        storage_for(state).ensure_ready()
    with pytest.raises(WorkImportDeferred):
        storage_for(state).connect(True)
    assert _sha(legacy) == sha and legacy.stat().st_mode & 0o200
    assert not (legacy.parent / "IMPORTED.json").exists()
    with closing(sqlite3.connect(state / "carnivore.db")) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'work_%'").fetchall() == []
    monkeypatch.setattr(copy, "digest", real)
    time.sleep(1.1)
    ready.forget(state / "carnivore.db")
    storage_for(state).ensure_ready()
    with closing(storage_for(state).connect(False)) as conn:
        assert conn.execute("SELECT kind FROM work_imports").fetchone()[0] == "import"


@pytest.mark.parametrize("damage", ["newer", "unknown_table"])
def test_a_file_this_build_cannot_vouch_for_defers(state: Path, damage: str) -> None:
    legacy = _legacy(state)
    with closing(sqlite3.connect(legacy)) as conn:
        conn.execute(f"PRAGMA user_version = {LEGACY_VERSION + 1}") if damage == "newer" else conn.execute("CREATE TABLE stray (x)")
        conn.commit()
    with pytest.raises(WorkImportDeferred):
        storage_for(state).ensure_ready()
    with closing(sqlite3.connect(state / "carnivore.db")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'work_%'").fetchone()[0] == 0


def test_a_restart_after_the_switch_imports_nothing_again(state: Path) -> None:
    legacy = _legacy(state)
    storage_for(state).ensure_ready()
    with closing(storage_for(state).connect(True)) as conn:
        conn.execute("UPDATE work_items SET text = 'written after the switch' WHERE id = 2")
        conn.commit()
    marker = (legacy.parent / "IMPORTED.json").read_bytes()
    ready.forget(state / "carnivore.db")
    storage_for(state).ensure_ready()
    with closing(storage_for(state).connect(False)) as conn:
        assert conn.execute("SELECT text FROM work_items WHERE id = 2").fetchone()[0] == "written after the switch"
        assert conn.execute("SELECT COUNT(*) FROM work_imports").fetchone()[0] == 1
    assert len(list(legacy.parent.glob("huddle.db.pre-work-import-*"))) == 1 and (legacy.parent / "IMPORTED.json").read_bytes() == marker


def test_work_tables_without_a_switch_defer(state: Path) -> None:
    with closing(sqlite3.connect(state / "carnivore.db")) as conn:
        conn.execute("CREATE TABLE work_items (id INTEGER PRIMARY KEY)")
    with pytest.raises(WorkImportDeferred, match="no import record"):
        storage_for(state).ensure_ready()


@pytest.fixture
def fresh(state: Path) -> sqlite3.Connection:
    storage = WorkStorage(state)
    with closing(storage.connect(True)) as conn:
        conn.execute("INSERT INTO work_items (id, list_key, text, position, created_by, state, created_at, updated_at, created_seq, seq, "
                     "claude_working, claude_working_by, owner_session_key) VALUES (1, '7', 't', 1, 'joe', 'open', 1, 1, 1, 1, 1, 's1', 's1')")
        conn.commit()
        yield conn


def _item(conn: sqlite3.Connection) -> dict:
    return dict(conn.execute("SELECT state, claude_working, claude_working_by, owner_session_key FROM work_items WHERE id = 1").fetchone())


def test_the_claim_ends_when_a_task_leaves_open(fresh: sqlite3.Connection) -> None:
    fresh.execute("UPDATE work_items SET state = 'review' WHERE id = 1")
    assert _item(fresh)["claude_working"] == 0 and _item(fresh)["claude_working_by"] == ""


def test_the_owner_follows_the_claim_and_is_released_on_done(fresh: sqlite3.Connection) -> None:
    fresh.execute("UPDATE work_items SET claude_working_by = 's2' WHERE id = 1")
    assert _item(fresh)["owner_session_key"] == "s2"
    fresh.execute("UPDATE work_items SET state = 'done' WHERE id = 1")
    assert _item(fresh)["owner_session_key"] == ""


def test_the_owner_is_released_on_delete(fresh: sqlite3.Connection) -> None:
    fresh.execute("UPDATE work_items SET deleted = 1 WHERE id = 1")
    assert _item(fresh)["owner_session_key"] == ""


@pytest.mark.parametrize(("change", "status"), [("state = 'review'", "settled"), ("state = 'open'", "ended"), ("deleted = 1", "ended")])
def test_a_wait_ends_when_its_task_leaves_waiting_or_is_deleted(fresh: sqlite3.Connection, change: str, status: str) -> None:
    cols = {r[1]: r for r in fresh.execute("PRAGMA table_info(work_item_waits)")}
    fresh.execute("UPDATE work_items SET state = 'waiting' WHERE id = 1")
    required = [c for c, r in cols.items() if r[3] and r[4] is None and not r[5]]
    values = {c: ("active" if c == "status" else 1 if c == "item_id" else "x") for c in required}
    fresh.execute(f"INSERT INTO work_item_waits ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})", list(values.values()))
    fresh.execute(f"UPDATE work_items SET {change} WHERE id = 1")
    assert fresh.execute("SELECT status FROM work_item_waits WHERE item_id = 1").fetchone()[0] == status
