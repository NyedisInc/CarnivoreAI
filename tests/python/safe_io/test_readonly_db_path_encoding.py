
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from src.core.safe_io.readonly_db import connect_readonly

TRICKY_DIRS = ("a#b", "50%25off", "q?x")


def _make(path: Path, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE t (v TEXT)")
        conn.execute("INSERT INTO t VALUES (?)", (marker,))
        conn.commit()


@pytest.mark.parametrize("name", TRICKY_DIRS)
def test_special_characters_open_the_named_file(tmp_path: Path, name: str) -> None:
    _make(tmp_path / name / "x.db", "right")
    _make(tmp_path / name.split("#")[0].split("%")[0].split("?")[0] / "x.db", "wrong")
    with closing(connect_readonly(tmp_path / name / "x.db")) as conn:
        assert conn.execute("SELECT v FROM t").fetchone()[0] == "right"


def test_read_only_and_never_creates(tmp_path: Path) -> None:
    _make(tmp_path / "d.db", "v")
    with closing(connect_readonly(tmp_path / "d.db")) as conn:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO t VALUES ('x')")
    with pytest.raises(sqlite3.OperationalError):
        connect_readonly(tmp_path / "nope.db")
    assert not (tmp_path / "nope.db").exists()
