
from __future__ import annotations

from contextlib import closing

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_steps import run_chain


def test_v57_database_upgrades_with_table_column_and_index(tmp_path):
    with closing(connect(db_path_for(tmp_path))) as conn:
        run_chain(conn, 0, 57)
        conn.execute(
            "INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at) "
            "VALUES ('/r', '/r', 'old', 'user', 'x', 'x')"
        )
        assert "company_id" not in {r[1] for r in conn.execute("PRAGMA table_info(projects)")}
        with conn:
            run_chain(conn, 57, 58)
        assert CURRENT_SCHEMA_VERSION >= 58
        assert {r[1] for r in conn.execute("PRAGMA table_info(companies)")} == {"id", "name", "created_at", "updated_at"}
        assert "company_id" in {r[1] for r in conn.execute("PRAGMA table_info(projects)")}
        assert conn.execute("SELECT company_id FROM projects").fetchone()[0] is None
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'ix_projects_company'").fetchone()
        conn.execute("INSERT INTO companies (name, created_at, updated_at) VALUES ('Acme', 'x', 'x')")
        try:
            conn.execute("INSERT INTO companies (name, created_at, updated_at) VALUES ('ACME', 'x', 'x')")
        except Exception as exc:  # noqa: BLE001
            assert "UNIQUE" in str(exc)
        else:
            raise AssertionError("names are unique case-insensitively")


def test_fresh_install_is_current_and_step_is_idempotent(tmp_path):
    assert ensure_db_migrated(tmp_path, 4, "0.0.0").schema_version == CURRENT_SCHEMA_VERSION
    from src.core.companies.ddl import apply_v58

    with closing(connect(db_path_for(tmp_path))) as conn:
        apply_v58(conn)
