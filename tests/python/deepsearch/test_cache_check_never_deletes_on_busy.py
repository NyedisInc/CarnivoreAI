
from __future__ import annotations

import sqlite3
from pathlib import Path

from src.core.deepsearch.cache import db as cache_db


def _cache(tmp_path: Path) -> Path:
    path = cache_db.cache_path(tmp_path)
    sqlite3.connect(path).close()
    cache_db._checked.discard(str(path))
    return path


def test_an_operational_error_keeps_the_files_and_retries(tmp_path: Path, monkeypatch) -> None:
    path = _cache(tmp_path)

    def locked(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cache_db.sqlite3, "connect", locked)
    cache_db.ensure_checked(path)
    monkeypatch.undo()
    assert path.exists()
    assert str(path) not in cache_db._checked


def test_a_file_that_is_not_a_database_is_still_reset(tmp_path: Path) -> None:
    path = cache_db.cache_path(tmp_path)
    path.write_bytes(b"this is not a sqlite file" * 100)
    cache_db._checked.discard(str(path))
    cache_db.ensure_checked(path)
    assert not path.exists()
