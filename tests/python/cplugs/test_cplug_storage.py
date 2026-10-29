
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.storage import LEGACY_STORAGE, WorkStorage
from src.cplugs.sdk import CplugStorage


def make_legacy(state_dir: Path) -> Path:
    old = state_dir / "huddle.db"
    CplugStorage(state_dir, LEGACY_STORAGE).connect(True).close()
    with closing(sqlite3.connect(old)) as conn, conn:
        for n, (key, text, by) in enumerate((("all", "one", "joe"), ("12", "two", "claude")), 1):
            conn.execute("INSERT INTO items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, seq) "
                         "VALUES (?, ?, 0, ?, 'open', 1, 1, ?, ?)", (key, text, by, n, n))
        conn.execute("UPDATE meta SET v = 2 WHERE k = 'seq'")
    assert old.exists()
    return old


def test_the_old_file_moves_in_once_and_keeps_its_rows(tmp_path: Path):
    old = make_legacy(tmp_path)
    storage = WorkStorage(tmp_path / "cplugs" / "huddle", tmp_path)
    store = TaskManagerStore(storage, notify=lambda key: None)
    assert [i["text"] for i in store.list_items("all")["items"]] == ["one"]
    assert [i["text"] for i in store.list_items("12")["items"]] == ["two"]
    assert (tmp_path / "cplugs" / "huddle" / "huddle.db").exists()
    with sqlite3.connect(old) as conn:
        assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2
    assert not list((tmp_path / "cplugs" / "huddle").glob(".*moving*"))
    with sqlite3.connect(old) as conn:
        conn.execute("CREATE TABLE stray (x)")
    store.add("all", "three", actor="joe")
    assert [i["text"] for i in TaskManagerStore(storage, notify=lambda key: None).list_items("all")["items"]] == ["one", "three"]
    assert old.exists()


def test_a_read_with_no_file_creates_nothing(tmp_path: Path):
    storage = WorkStorage(tmp_path / "cplugs" / "huddle", tmp_path)
    assert TaskManagerStore(storage, notify=lambda key: None).list_items("all")["items"] == []
    assert not (tmp_path / "cplugs").exists()


def test_openers_racing_on_a_file_that_needs_migrating_walk_the_ladder_once(tmp_path: Path):
    import threading

    for round_ in range(15):
        storage = CplugStorage(tmp_path / f"r{round_}", LEGACY_STORAGE, tmp_path)
        gate = threading.Barrier(6)
        errors: list = []

        def opener() -> None:
            gate.wait()
            try:
                storage.connect(True).close()
            except sqlite3.Error as exc:
                errors.append(exc)

        threads = [threading.Thread(target=opener) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == [], errors
        with storage.connect(False) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == storage.schema_version
