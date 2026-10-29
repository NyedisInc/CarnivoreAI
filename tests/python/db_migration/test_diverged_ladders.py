
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from src.core.db import connect, db_path_for, get_schema_version, set_meta
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import CURRENT_SCHEMA_VERSION, META_SCHEMA_VERSION
from src.core.db_steps import run_chain
from src.core.project_colors.ddl import apply_v61
from src.core.work.ladder import MIGRATIONS, SCHEMA_VERSION, feature_rungs
from src.core.work.storage import LEGACY_STORAGE
from src.cplugs.sdk import CplugSchemaError, CplugStorage
from src.cplugs.sdk.storage_reconcile import master_rows


def _cloude_master(state_dir: Path) -> frozenset:
    with closing(sqlite3.connect(db_path_for(state_dir))) as conn:
        return master_rows(conn)


def _fresh_cloude(tmp_path: Path) -> frozenset:
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    assert ensure_db_migrated(fresh).status == "ok"
    return _cloude_master(fresh)


def _joe_cloude(state_dir: Path) -> list:
    with closing(connect(db_path_for(state_dir))) as conn:
        with conn:
            run_chain(conn, 0, 58)
            for i in range(10):
                conn.execute("INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at) "
                             f"VALUES ('/p{i}', '/p{i}', 'p{i}', 'user', 'x', 'x')")
            apply_v61(conn)
            set_meta(conn, META_SCHEMA_VERSION, "59")
        conn.execute("UPDATE projects SET color = '#966356' WHERE id = 3")
        conn.commit()
        return conn.execute("SELECT id, color FROM projects ORDER BY id").fetchall()


def test_a_cloude_db_diverged_at_59_ends_equal_to_a_fresh_one_with_its_colors(tmp_path: Path) -> None:
    state_dir = tmp_path / "joe"
    state_dir.mkdir()
    colors = _joe_cloude(state_dir)
    state = ensure_db_migrated(state_dir)
    assert state.status == "ok" and state.schema_version == CURRENT_SCHEMA_VERSION
    assert "repair:swarm_agents" in state.migrations_applied
    assert "repair:swarm_repo_visibility.remote_fingerprint" in state.migrations_applied
    assert _cloude_master(state_dir) == _fresh_cloude(tmp_path)
    with closing(connect(db_path_for(state_dir))) as conn:
        assert len([r[1] for r in colors if r[1]]) == 10
        assert [tuple(r) for r in conn.execute("SELECT id, color FROM projects ORDER BY id")] == [
            (pid, color if color == "#966356" else None) for pid, color in map(tuple, colors)]
        assert get_schema_version(conn) == CURRENT_SCHEMA_VERSION
    again = ensure_db_migrated(state_dir)
    assert again.status == "ok" and not again.migrations_applied


def test_a_fresh_cloude_db_needs_no_repair(tmp_path: Path) -> None:
    state = ensure_db_migrated(tmp_path)
    assert state.status == "ok"
    assert not [step for step in state.migrations_applied if step.startswith("repair:")]


@pytest.mark.parametrize("start", [60, CURRENT_SCHEMA_VERSION])
def test_a_master_cloude_db_migrates_exactly_as_before(tmp_path: Path, start: int) -> None:
    state_dir = tmp_path / "alex"
    state_dir.mkdir()
    with closing(connect(db_path_for(state_dir))) as conn:
        with conn:
            run_chain(conn, 0, start)
    before = _cloude_master(state_dir)
    state = ensure_db_migrated(state_dir)
    assert state.status == "ok"
    assert not [step for step in (state.migrations_applied or []) if step.startswith("repair:")]
    assert _cloude_master(state_dir) == _fresh_cloude(tmp_path)
    if start == CURRENT_SCHEMA_VERSION:
        assert _cloude_master(state_dir) == before


def _huddle_master(folder: Path) -> frozenset:
    with closing(sqlite3.connect(folder / "huddle.db")) as conn:
        return master_rows(conn)


def _fresh_huddle(tmp_path: Path) -> frozenset:
    folder = tmp_path / "fresh-huddle"
    CplugStorage(folder, LEGACY_STORAGE).connect(write=True).close()
    return _huddle_master(folder)


JOES_TRIGGERS_RUNG = (
    "CREATE TABLE item_triggers ("
    "item_id INTEGER PRIMARY KEY REFERENCES items (id), "
    "kind TEXT NOT NULL DEFAULT 'at', "
    "fire_at REAL, "
    "fired_at REAL, "
    "last_error TEXT, "
    "updated_at REAL NOT NULL);"
    "CREATE INDEX item_triggers_due ON item_triggers (fire_at) WHERE fired_at IS NULL;"
)
NEEDS_RUNG_16 = pytest.mark.skipif(SCHEMA_VERSION < 16, reason="the scheduled-todos rung (16) is not in this tree")


def _ladder_file(folder: Path, ladder: list) -> sqlite3.Connection:
    folder.mkdir(parents=True)
    conn = sqlite3.connect(folder / "huddle.db")
    for script in ladder:
        conn.executescript(f"BEGIN; {script} COMMIT;")
    conn.execute(f"PRAGMA user_version = {len(ladder)}")
    return conn


def _seed(conn: sqlite3.Connection) -> None:
    for i in range(1, 5):
        conn.execute("INSERT INTO items (list_key, text, position, created_by, state, created_at, updated_at, "
                     f"created_seq, seq, deleted) VALUES ('all', 'row {i}', {i}, 'joe', 'open', 1, 1, {i}, {i}, 0)")
    conn.execute("DELETE FROM items WHERE id = 4")
    for item in (1, 2):
        conn.execute("INSERT INTO messages (item_id, author, kind, text, created_at, seq) "
                     f"VALUES ({item}, 'claude', 'info', 'm{item}', 1, 9)")


def test_a_huddle_db_diverged_at_14_ends_equal_to_a_fresh_one_with_its_claims(tmp_path: Path) -> None:
    folder = tmp_path / "joe-huddle-14"
    with closing(_ladder_file(folder, list(MIGRATIONS[:13]) + [feature_rungs.CLAIM_MIGRATION])) as conn:
        _seed(conn)
        conn.execute("UPDATE items SET claude_working = 1, claude_working_by = 'ses_a' WHERE id = 2")
        conn.commit()
        counter_before = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'items'").fetchone()[0]
    CplugStorage(folder, LEGACY_STORAGE).connect(write=True).close()
    assert _huddle_master(folder) == _fresh_huddle(tmp_path)
    with closing(sqlite3.connect(folder / "huddle.db")) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert conn.execute("SELECT claude_working, claude_working_by FROM items WHERE id = 2").fetchone() == (1, "ses_a")
        assert conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'items'").fetchone()[0] == counter_before
        assert {r[0] for r in conn.execute("SELECT author_key FROM messages")} == {""}
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


@NEEDS_RUNG_16
def test_a_huddle_db_diverged_at_15_ends_equal_to_a_fresh_one_with_claims_and_triggers(tmp_path: Path) -> None:
    folder = tmp_path / "joe-huddle"
    joe_ladder = list(MIGRATIONS[:13]) + [feature_rungs.CLAIM_MIGRATION, JOES_TRIGGERS_RUNG]
    with closing(_ladder_file(folder, joe_ladder)) as conn:
        _seed(conn)
        conn.execute("UPDATE items SET claude_working = 1, claude_working_by = 'ses_a' WHERE id = 2")
        conn.execute("INSERT INTO item_triggers (item_id, fire_at, updated_at) VALUES (1, 4102444800, 1)")
        conn.commit()
        items_before = conn.execute("SELECT * FROM items ORDER BY id").fetchall()
        names_before = [c[1] for c in conn.execute("PRAGMA table_info(items)")]
        triggers_before = conn.execute("SELECT item_id, kind, fire_at, fired_at, last_error, updated_at FROM item_triggers").fetchall()
        counter_before = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'items'").fetchone()[0]
    CplugStorage(folder, LEGACY_STORAGE).connect(write=True).close()
    assert _huddle_master(folder) == _fresh_huddle(tmp_path)
    with closing(sqlite3.connect(folder / "huddle.db")) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        cols = ", ".join(names_before)
        assert conn.execute(f"SELECT {cols} FROM items ORDER BY id").fetchall() == items_before
        assert conn.execute("SELECT claude_working, claude_working_by FROM items WHERE id = 2").fetchone() == (1, "ses_a")
        assert conn.execute("SELECT item_id, kind, fire_at, fired_at, last_error, updated_at FROM item_triggers").fetchall() == triggers_before
        assert conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'items'").fetchone()[0] == counter_before
        assert {r[0] for r in conn.execute("SELECT author_key FROM messages")} == {""}
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_a_master_huddle_db_at_15_walks_the_ladder_as_before(tmp_path: Path) -> None:
    folder = tmp_path / "alex-huddle"
    with closing(_ladder_file(folder, list(MIGRATIONS[:15]))) as conn:
        _seed(conn)
        conn.commit()
    CplugStorage(folder, LEGACY_STORAGE).connect(write=True).close()
    assert _huddle_master(folder) == _fresh_huddle(tmp_path)


def test_a_fresh_huddle_db_is_the_ladder(tmp_path: Path) -> None:
    folder = tmp_path / "new"
    conn = CplugStorage(folder, LEGACY_STORAGE).connect(write=True)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        conn.close()


@NEEDS_RUNG_16
def test_a_huddle_db_with_a_rung_half_present_is_refused_and_left_alone(tmp_path: Path) -> None:
    folder = tmp_path / "half"
    joe_ladder = list(MIGRATIONS[:13]) + [feature_rungs.CLAIM_MIGRATION]
    with closing(_ladder_file(folder, joe_ladder)) as conn:
        conn.execute("PRAGMA user_version = 15")
        conn.execute("CREATE TABLE item_triggers (item_id INTEGER PRIMARY KEY)")
        conn.commit()
    before = (folder / "huddle.db").read_bytes()
    with pytest.raises(CplugSchemaError, match="partly present"):
        CplugStorage(folder, LEGACY_STORAGE).connect(write=True)
    assert (folder / "huddle.db").read_bytes() == before
