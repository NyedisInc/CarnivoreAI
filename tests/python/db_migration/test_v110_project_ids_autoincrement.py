
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_state import STATUS_DEGRADED_MIGRATION_FAILED
from src.core.db_schema_audit import AUDIT_OK, audit_schema, repair_after_chain
from src.core.db_steps import run_chain
from src.core.automations import store_schema
from src.core.project_ids.ddl import _AUTOINCREMENT_ID, ProjectIdsMigrationError, apply_v110

STAMP = "2026-11-18T00:00:00Z"


def _project(conn: sqlite3.Connection, pid: int, name: str) -> None:
    conn.execute("INSERT INTO projects (id, root, raw_path, display_name, source, created_at, updated_at) "
                 "VALUES (?, ?, ?, ?, 'user', ?, ?)", (pid, f"/p/{name}", f"/p/{name}", name, STAMP, STAMP))


def _v109(state_dir: Path) -> Path:
    path = db_path_for(state_dir)
    with closing(connect(path)) as conn:
        with conn:
            run_chain(conn, 0, 109)
            _project(conn, 1, "one")
            _project(conn, 2, "two")
            conn.execute("INSERT INTO companies (id, name, created_at, updated_at, hq_project_id) VALUES (1, 'c', ?, ?, 2)",
                         (STAMP, STAMP))
            conn.execute("UPDATE projects SET company_id = 1 WHERE id = 1")
            conn.execute("INSERT INTO swarm_project_settings (project_id, promotion_threshold) VALUES (2, 7)")
            conn.execute("INSERT INTO sessions (session_uuid, working_dir, origin, created_at, updated_at, project_id) "
                         "VALUES ('s-1', '/p/one', 'created', ?, ?, 1)", (STAMP, STAMP))
            conn.execute("CREATE TABLE work_items (id INTEGER PRIMARY KEY AUTOINCREMENT, list_key TEXT NOT NULL, "
                         "from_project_id TEXT)")
            conn.execute("CREATE TABLE work_card_grants (scope TEXT PRIMARY KEY, slots INTEGER NOT NULL)")
            conn.executemany("INSERT INTO work_items (list_key, from_project_id) VALUES (?, ?)",
                             [("12", None), ("agent:900", None), ("2", "41")])
            conn.executemany("INSERT INTO work_card_grants VALUES (?, ?)", [("project:55", 2), ("sysop", 1)])
    return path


SchemaRow = Tuple[str, str, str, Optional[str]]


_POST_V110_TABLES = (
    "session_groups",
    "installed_items",
    "pack_rollups",
    "pack_rollup_state",
    "pack_rollups_5m",
    "pack_rollup_activity",
    "pack_rollup_quota",
    "pack_rollup_conversations",
    "pack_rollup_events",
    "pack_rollup_coverage",
    "pack_rollup_mcp",
)


def _schema(conn: sqlite3.Connection) -> List[SchemaRow]:
    marks = ",".join("?" * len(_POST_V110_TABLES))
    return sorted(tuple(r) for r in conn.execute(
        f"SELECT type, name, tbl_name, sql FROM sqlite_master WHERE tbl_name NOT IN ({marks})",
        _POST_V110_TABLES,
    ))


def _rows(conn: sqlite3.Connection) -> Dict[str, List[Tuple[object, ...]]]:
    return {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
            for t in ("projects", "companies", "swarm_project_settings", "sessions", "work_items", "work_card_grants")}


def test_the_migrator_backs_up_then_adds_autoincrement_and_seeds_above_every_reference(tmp_path: Path) -> None:
    path = _v109(tmp_path)
    with closing(sqlite3.connect(path)) as conn:
        before_schema, before_rows = _schema(conn), _rows(conn)
        before_fks = conn.execute("PRAGMA foreign_key_list(projects)").fetchall()
    state = ensure_db_migrated(tmp_path)
    assert state.status == "ok" and CURRENT_SCHEMA_VERSION >= 110
    [backup] = list(tmp_path.glob("*.bak-v109-*"))
    with closing(sqlite3.connect(backup)) as conn:
        assert _schema(conn) == before_schema
    with closing(sqlite3.connect(path)) as conn:
        after_schema = _schema(conn)
        assert _rows(conn) == before_rows
        assert conn.execute("PRAGMA foreign_key_list(projects)").fetchall() == before_fks
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'projects'").fetchone()[0] == 55
    changed = [(a, b) for a, b in zip(before_schema, after_schema) if a != b]
    assert len(before_schema) == len(after_schema) and len(changed) == 1
    (old, new), = changed
    assert old[1] == "projects" and "AUTOINCREMENT" not in old[3]
    assert new[3] == old[3].replace("INTEGER PRIMARY KEY,", "INTEGER PRIMARY KEY AUTOINCREMENT,", 1)

    with closing(connect(path)) as conn:
        with conn:
            conn.execute("INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at) "
                         "VALUES ('/p/new', '/p/new', 'new', 'user', ?, ?)", (STAMP, STAMP))
        assert conn.execute("SELECT id FROM projects WHERE root = '/p/new'").fetchone()[0] == 56

    with closing(sqlite3.connect(path)) as conn:
        settled = _schema(conn), conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'projects'").fetchone()[0]
    assert ensure_db_migrated(tmp_path).status == "ok"
    with closing(sqlite3.connect(path)) as conn:
        with conn:
            apply_v110(conn)
        assert (_schema(conn), conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'projects'").fetchone()[0]) == settled
    assert len(list(tmp_path.glob("*.bak-v109-*"))) == 1


def test_a_fresh_database_gets_autoincrement_from_the_chain(tmp_path: Path) -> None:
    assert ensure_db_migrated(tmp_path).status == "ok"
    with closing(sqlite3.connect(db_path_for(tmp_path))) as conn:
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'projects'").fetchone()[0]
    assert "id                  INTEGER PRIMARY KEY AUTOINCREMENT," in sql


def test_an_unexpected_id_column_is_refused_not_guessed(tmp_path: Path) -> None:
    with closing(sqlite3.connect(tmp_path / "odd.db")) as conn:
        conn.execute("CREATE TABLE projects (root TEXT, id INTEGER NOT NULL PRIMARY KEY)")
        with pytest.raises(ProjectIdsMigrationError):
            apply_v110(conn)


def _projects_seq(path: Path) -> int:
    with closing(sqlite3.connect(path)) as conn:
        return int(conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'projects'").fetchone()[0])


def test_a_connection_opened_before_the_migration_does_not_reuse_an_id(tmp_path: Path) -> None:
    path = _v109(tmp_path)
    with closing(sqlite3.connect(path, isolation_level=None)) as early:
        early.execute("SELECT id FROM projects").fetchall()
        assert ensure_db_migrated(tmp_path).status == "ok"
        with closing(sqlite3.connect(path, isolation_level=None)) as conn:
            conn.execute("DELETE FROM swarm_project_settings WHERE project_id = 2")
            conn.execute("UPDATE companies SET hq_project_id = NULL")
            conn.execute("DELETE FROM projects WHERE id = 2")
        early.execute("INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at) "
                      "VALUES ('/p/late', '/p/late', 'late', 'user', ?, ?)", (STAMP, STAMP))
        new_id = early.execute("SELECT id FROM projects WHERE root = '/p/late'").fetchone()[0]
    assert new_id > 55, f"a connection opened before v110 handed out id {new_id}"


def test_the_seed_reads_automations_db_beside_the_database(tmp_path: Path) -> None:
    path = _v109(tmp_path)
    folder = path.parent / store_schema.FOLDER_NAME
    folder.mkdir()
    with closing(sqlite3.connect(folder / store_schema.DB_NAME)) as conn:
        with conn:
            conn.execute("CREATE TABLE automations (automation_id TEXT PRIMARY KEY, project_id INTEGER)")
            conn.executemany("INSERT INTO automations VALUES (?, ?)", [("a", 77), ("b", None), ("c", 1)])
    assert ensure_db_migrated(tmp_path).status == "ok"
    assert _projects_seq(path) == 77
    from src.core.project_ids import ddl
    assert (ddl.AUTOMATIONS_FOLDER, ddl.AUTOMATIONS_DB) == (store_schema.FOLDER_NAME, store_schema.DB_NAME)


def test_an_unreadable_automations_db_is_skipped_not_fatal(tmp_path: Path) -> None:
    path = _v109(tmp_path)
    folder = path.parent / store_schema.FOLDER_NAME
    folder.mkdir()
    (folder / store_schema.DB_NAME).write_bytes(b"not a database at all, just bytes" * 8)
    assert ensure_db_migrated(tmp_path).status == "ok"
    assert _projects_seq(path) == 55


def test_the_seed_reads_a_leftover_swarm_thread_key(tmp_path: Path) -> None:
    path = _v109(tmp_path)
    with closing(sqlite3.connect(path)) as conn:
        with conn:
            conn.execute(
                "INSERT INTO swarm_agents (slug, rank, display_name, job, repo_dir, memory_scope, effort, character_seed, "
                "color_slot, thread_key, created_at, updated_at) VALUES ('p', 'project', 'p', 'j', '/p', 'project', 'low', 1, 1, "
                "'88', ?, ?)", (STAMP, STAMP))
    assert ensure_db_migrated(tmp_path).status == "ok"
    assert _projects_seq(path) == 88


def test_the_audit_repair_recreates_projects_with_autoincrement(tmp_path: Path) -> None:
    path = db_path_for(tmp_path)
    with closing(connect(path)) as conn:
        with conn:
            run_chain(conn, 0, CURRENT_SCHEMA_VERSION)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("DROP TABLE projects")
        conn.commit()
    with closing(connect(path)) as conn:
        with conn:
            repaired = repair_after_chain(conn, CURRENT_SCHEMA_VERSION)
        assert "repair:projects" in repaired
        assert audit_schema(conn, CURRENT_SCHEMA_VERSION).status == AUDIT_OK
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'projects'").fetchone()[0]
    assert "INTEGER PRIMARY KEY AUTOINCREMENT," in sql


def _v109_unreferenced_top(state_dir: Path) -> Path:
    path = db_path_for(state_dir)
    with closing(connect(path)) as conn:
        with conn:
            run_chain(conn, 0, 109)
            for pid in range(1, 10):
                _project(conn, pid, f"p{pid}")
            conn.execute("INSERT INTO sessions (session_uuid, working_dir, origin, created_at, updated_at, project_id) "
                         "VALUES ('s-5', '/p/p5', 'created', ?, ?, 5)", (STAMP, STAMP))
    return path


def _insert_new_project(path: Path, name: str) -> int:
    with closing(connect(path)) as conn:
        with conn:
            conn.execute("INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at) "
                         "VALUES (?, ?, ?, 'user', ?, ?)", (f"/p/{name}", f"/p/{name}", name, STAMP, STAMP))
        return int(conn.execute("SELECT id FROM projects WHERE root = ?", (f"/p/{name}",)).fetchone()[0])


def test_a_live_unreferenced_top_project_id_is_never_reissued_after_it_is_deleted(tmp_path: Path) -> None:
    path = _v109_unreferenced_top(tmp_path)
    assert ensure_db_migrated(tmp_path).status == "ok"
    assert _projects_seq(path) == 9
    with closing(sqlite3.connect(path)) as conn:
        with conn:
            conn.execute("DELETE FROM projects WHERE id = 9")
    assert _insert_new_project(path, "fresh") == 10


def test_the_audit_repair_seed_counts_the_live_projects_too(tmp_path: Path) -> None:
    from src.core.project_ids.ddl import highest_project_id
    path = _v109_unreferenced_top(tmp_path)
    with closing(sqlite3.connect(path)) as conn:
        assert highest_project_id(conn) == 9


def test_a_failing_v110_rolls_the_whole_migration_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.project_ids import ddl
    path = _v109(tmp_path)
    with closing(sqlite3.connect(path)) as conn:
        before_schema, before_rows = _schema(conn), _rows(conn)
        before_version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
    real, calls = ddl._fk_report, []

    def report_that_changes(conn: sqlite3.Connection) -> list:
        calls.append(1)
        return real(conn) + ([("projects", 1, "projects", 0)] if len(calls) > 1 else [])

    monkeypatch.setattr(ddl, "_fk_report", report_that_changes)
    state = ensure_db_migrated(tmp_path)
    assert len(calls) == 2, "the failure must come from the step's own check, after the edit"
    assert state.status == STATUS_DEGRADED_MIGRATION_FAILED
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == before_version
        assert _schema(conn) == before_schema
        assert _rows(conn) == before_rows
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_the_stored_projects_schema_keeps_autoincrement(tmp_path: Path) -> None:
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    migrated = tmp_path / "migrated"
    migrated.mkdir()
    assert ensure_db_migrated(fresh).status == "ok"
    _v109(migrated)
    assert ensure_db_migrated(migrated).status == "ok"
    for folder in (fresh, migrated):
        with closing(sqlite3.connect(db_path_for(folder))) as conn:
            sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'projects'").fetchone()[0]
        assert _AUTOINCREMENT_ID.search(sql), f"{folder.name}: projects lost AUTOINCREMENT: {sql[:120]!r}"


def test_a_digit_string_past_the_javascript_safe_integer_is_not_a_project_id(tmp_path: Path) -> None:
    path = _v109(tmp_path)
    with closing(sqlite3.connect(path)) as conn:
        with conn:
            conn.execute("INSERT INTO work_card_grants VALUES ('9007199254740993', 1)")
            conn.execute("INSERT INTO work_card_grants VALUES ('1732000000000000000', 1)")
    assert ensure_db_migrated(tmp_path).status == "ok"
    assert _projects_seq(path) == 55
