
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import os
import shutil
import sqlite3
import stat
from contextlib import closing
from pathlib import Path
from typing import Dict, Optional

import pytest
from fastapi import FastAPI

from src.core.work.capability import WorkCapability
from src.core.work.importer import ready
from src.core.work.storage import DB_NAME, LEGACY_STORAGE, folder
from src.cplugs.host import runtime
from src.cplugs.sdk import CplugSchemaError, CplugStorage, StorageSpec
from tests.python.cplugs.owner import turn_on

ITEM_SQL = ("INSERT INTO items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, seq) "
            "VALUES (?, ?, 0, ?, 'open', 1, 1, ?, ?)")
REPLY_SQL = "INSERT INTO messages (item_id, author, kind, text, created_at, seq) VALUES (?, 'joe', 'reply', 'a reply', 2, 3)"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seeded_copy(state_dir: Path, spec: StorageSpec = LEGACY_STORAGE, items: int = 2) -> Path:
    scratch = state_dir / "scratch"
    CplugStorage(scratch, spec).connect(True).close()
    with closing(sqlite3.connect(scratch / DB_NAME)) as conn, conn:
        first = conn.execute(ITEM_SQL, ("all", "ship it", "joe", 1, 1)).lastrowid
        if items > 1:
            conn.execute(ITEM_SQL, ("12", "second", "claude", 2, 2))
        conn.execute(REPLY_SQL, (first,))
        conn.execute("UPDATE meta SET v = 3 WHERE k = 'seq'")
    target = folder(state_dir) / DB_NAME
    target.parent.mkdir(parents=True)
    with closing(sqlite3.connect(scratch / DB_NAME)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
    return target


def listing(path: Path) -> Dict[str, int]:
    return {p.name: p.stat().st_size for p in path.parent.iterdir()}


def work_count(work: WorkCapability, sql: str) -> int:
    with closing(work.storage.connect(False)) as conn:
        return conn.execute(sql).fetchone()[0]


def version(path: Path) -> int:
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


def work_tables(db: Path) -> Optional[list]:
    if not db.exists():
        return None
    with closing(sqlite3.connect(db)) as conn:
        return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'work\\_%' ESCAPE '\\'")]


def test_opening_a_copy_at_49_imports_it_and_leaves_its_sha256_unchanged(tmp_path: Path) -> None:
    copy = seeded_copy(tmp_path)
    before, files = sha256(copy), listing(copy)
    work = WorkCapability(tmp_path)
    work.open()
    assert work_count(work, "SELECT COUNT(*) FROM work_items") == 2
    assert work_count(work, "SELECT COUNT(*) FROM work_messages WHERE text = 'a reply'") == 1
    assert work_count(work, "SELECT COUNT(*) FROM work_imports WHERE kind = 'import'") == 1
    assert sha256(copy) == before and version(copy) == 49
    added = set(listing(copy)) - set(files)
    assert ready.MARKER in added and [n for n in added if n.startswith(f"{DB_NAME}.pre-work-import-")]
    assert not copy.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)


def test_a_file_at_48_walks_rung_49_and_keeps_its_rows(tmp_path: Path) -> None:
    old = dataclasses.replace(LEGACY_STORAGE, migrations=tuple(LEGACY_STORAGE.migrations[:48]))
    target = seeded_copy(tmp_path, old, items=1)
    with closing(sqlite3.connect(target)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 48
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'held_tells'").fetchone() is None
    work = WorkCapability(tmp_path)
    work.open()
    assert version(target) == 49
    assert work_count(work, "SELECT COUNT(*) FROM work_held_sends") == 0
    assert work_count(work, "SELECT COUNT(*) FROM work_items") == 1
    assert work_count(work, "SELECT COUNT(*) FROM work_messages WHERE text = 'a reply'") == 1


def test_the_optional_live_copy_imports_without_a_byte_changing(tmp_path: Path) -> None:
    path = os.environ.get("WORK_LIVE_COPY")
    if not path:
        pytest.skip("WORK_LIVE_COPY is not set")
    copy = folder(tmp_path) / DB_NAME
    copy.parent.mkdir(parents=True)
    shutil.copy2(path, copy)
    before = sha256(copy)
    assert before == sha256(Path(path)) and version(copy) == 49
    with closing(sqlite3.connect(copy)) as conn:
        legacy_items = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    work = WorkCapability(tmp_path)
    work.open()
    assert work_count(work, "SELECT COUNT(*) FROM work_items") == legacy_items
    assert sha256(copy) == before


def test_a_file_from_a_newer_build_is_refused_and_not_touched(tmp_path: Path) -> None:
    copy = seeded_copy(tmp_path)
    with closing(sqlite3.connect(copy)) as conn:
        conn.execute("PRAGMA user_version = 50")
    before = sha256(copy)
    with pytest.raises(CplugSchemaError):
        WorkCapability(tmp_path).open()
    assert sha256(copy) == before
    assert work_tables(tmp_path / "carnivore.db") in (None, [])


def test_a_walk_that_fails_leaves_the_server_booting_with_the_plugin_unavailable(tmp_path: Path) -> None:
    copy = seeded_copy(tmp_path)
    with closing(sqlite3.connect(copy)) as conn:
        conn.execute("PRAGMA user_version = 50")
    host = runtime.Host(tmp_path, FastAPI(), publish=lambda topic: None)
    turn_on(host)
    asyncio.run(host.start())
    assert "huddle" in host.unavailable
    assert version(copy) == 50


def test_a_healthy_file_starts_the_plugin(tmp_path: Path) -> None:
    seeded_copy(tmp_path)
    host = runtime.Host(tmp_path, FastAPI(), publish=lambda topic: None)
    turn_on(host)
    asyncio.run(host.start())
    try:
        assert "huddle" not in host.unavailable
    finally:
        asyncio.run(host.stop())
