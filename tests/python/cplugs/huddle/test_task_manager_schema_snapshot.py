
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

from src.core.schema_ledger.snapshot import dump_schema
from src.core.work.storage import LEGACY_STORAGE
from src.cplugs.sdk import CplugStorage

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "task_manager_fresh_schema.sql"


def fresh_schema(tmp_path: Path) -> str:
    folder = tmp_path / "cplugs" / "huddle"
    with closing(CplugStorage(folder, LEGACY_STORAGE, tmp_path).connect(write=True)) as conn:
        return dump_schema(conn)


def test_fresh_ladder_schema_is_pinned_byte_for_byte(tmp_path: Path) -> None:
    text = fresh_schema(tmp_path)
    if os.environ.get("TASK_MANAGER_SNAPSHOT_WRITE") == "1":
        FIXTURE.write_text(text, encoding="utf-8")
    assert text == FIXTURE.read_text(encoding="utf-8")


def test_the_snapshot_is_version_49_with_the_26_tables() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    assert text.startswith("-- user_version 49\n")
    assert text.count("-- table ") == 25


def test_dump_notices_a_one_byte_schema_change() -> None:
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("CREATE TABLE a (x INTEGER)")
        before = dump_schema(conn)
        conn.execute("CREATE INDEX a_x ON a (x)")
        assert dump_schema(conn) != before
