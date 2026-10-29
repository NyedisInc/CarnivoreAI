
from __future__ import annotations

import ast
import sqlite3
from contextlib import closing
from pathlib import Path

from scripts.schema_ledger.ladders import LADDERS
from src.core.schema_ledger.ledger import check_ledger, parse_ledger
from src.core.schema_ledger.snapshot import dump_schema
from src.core.work import ladder, tables
from src.core.work.storage import DB_NAME, LEGACY_STORAGE, folder
from src.cplugs.sdk.storage import CplugStorage


def storage_for(state_dir: Path) -> CplugStorage:
    return CplugStorage(folder(state_dir), LEGACY_STORAGE, state_dir)

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests" / "fixtures" / "task_manager_fresh_schema.sql"


def test_core_ladder_builds_the_p0_snapshot_byte_for_byte(tmp_path: Path) -> None:
    with closing(storage_for(tmp_path).connect(write=True)) as conn:
        assert dump_schema(conn) == FIXTURE.read_text(encoding="utf-8")


def test_the_ladder_has_49_rungs_and_the_file_lands_on_49(tmp_path: Path) -> None:
    assert len(ladder.MIGRATIONS) == ladder.SCHEMA_VERSION == 49 and len(LEGACY_STORAGE.migrations) == 49
    with closing(storage_for(tmp_path).connect(write=True)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 49
    assert (tmp_path / "cplugs" / "huddle" / DB_NAME).exists()


def test_every_rung_matches_its_ledger_hash() -> None:
    check_ledger(LADDERS["huddle"])
    assert len(parse_ledger(LADDERS["huddle"].path, "H")) == 49


def test_the_backups_are_the_eight_rungs_that_took_one_before() -> None:
    assert dict(LEGACY_STORAGE.backup_before) == {23: "pre-cards", 34: "pre-done", 35: "pre-waiting", 36: "pre-todo", 37: "pre-review",
                                           38: "pre-lane", 43: "pre-claim-rule", 47: "pre-lineage-fold"}


def test_the_legacy_names_are_exactly_the_tables_the_legacy_ladder_creates(tmp_path: Path) -> None:
    with closing(storage_for(tmp_path).connect(write=True)) as conn:
        found = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")} - {"sqlite_sequence"}
    assert found == set(tables.LEGACY_NAMES.values()) and len(tables.ALL) == len(set(tables.ALL)) == 25


def test_a_rung_lives_in_core_only_never_in_a_plugin_module() -> None:
    left = []
    for path in (ROOT / "src" / "cplugs" / "huddle").rglob("*.py"):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id.endswith("_MIGRATION") for t in node.targets):
                left.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert left == []


def test_the_ladder_check_can_go_red(tmp_path: Path) -> None:
    with closing(sqlite3.connect(":memory:")) as conn:
        for step in ladder.MIGRATIONS[:1]:
            conn.executescript(step)
        before = dump_schema(conn)
        conn.execute("CREATE INDEX stray ON items (note)")
        assert dump_schema(conn) != before
