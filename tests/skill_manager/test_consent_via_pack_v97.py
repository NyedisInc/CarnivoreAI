
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from src.core import db_models
from src.core.db import connect, db_path_for, get_schema_version, set_meta
from src.core.db_migration import ensure_db_migrated
from src.core.skills import install_by_reference
from src.core.skills.consent_via_ddl import (
    CONSENT_PACK, NEW_CONSENT_CHECK, OLD_CONSENT_CHECK, widen_consent_check,
)

STAMP = "2026-10-22T10:00:00.000000Z"


def _open(path: Path):
    return closing(connect(path, create=False))


def _stored_sql(conn) -> str:
    return conn.execute("SELECT sql FROM sqlite_master WHERE name = 'installed_items'").fetchone()[0]


@pytest.fixture()
def v96_state(tmp_path) -> Path:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    assert ensure_db_migrated(state_dir).status == "ok"
    with _open(db_path_for(state_dir)) as conn:
        sql = _stored_sql(conn)
        assert NEW_CONSENT_CHECK in sql
        conn.execute("PRAGMA writable_schema=ON")
        conn.execute("UPDATE sqlite_master SET sql = ? WHERE name = 'installed_items'", (sql.replace(NEW_CONSENT_CHECK, OLD_CONSENT_CHECK),))
        conn.execute("PRAGMA writable_schema=RESET")
        for n, via in enumerate(("one_click", "sheet", "blueprint")):
            conn.execute(
                "INSERT INTO installed_items (install_id, item_id, kind, publisher, name, version, digest, scope, project_path, "
                "auto_update, source_index_url, publisher_key_id, revision, installed_at, updated_at, consent_via) "
                "VALUES (?, ?, 'skill', 'acme', ?, '1.0.0', ?, 'global', '', 0, 'https://x.invalid/i.json', 'RWkey', 1, ?, ?, ?)",
                (f"i{n}", f"acme/s{n}", f"s{n}", "d" * 64, STAMP, STAMP, via))
            conn.execute("INSERT INTO installed_item_targets (install_id, harness, path) VALUES (?, 'claude', ?)", (f"i{n}", f"/h/s{n}"))
        set_meta(conn, db_models.META_SCHEMA_VERSION, "96")
        conn.commit()
    return state_dir


def _snapshot(conn):
    rows = [dict(r) for r in conn.execute("SELECT * FROM installed_items ORDER BY install_id")]
    kids = [tuple(r) for r in conn.execute("SELECT * FROM installed_item_targets ORDER BY install_id")]
    return rows, kids


def test_the_fixture_really_holds_the_old_constraint(v96_state):
    with _open(db_path_for(v96_state)) as conn:
        assert OLD_CONSENT_CHECK in _stored_sql(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE installed_items SET consent_via = ? WHERE install_id = 'i0'", (CONSENT_PACK,))


def test_v96_walks_to_v97_keeping_every_row_and_child_and_admitting_pack(v96_state):
    path = db_path_for(v96_state)
    with _open(path) as conn:
        before = _snapshot(conn)
    state = ensure_db_migrated(v96_state)
    assert state.status == "ok", state.message
    with _open(path) as conn:
        assert get_schema_version(conn) == db_models.CURRENT_SCHEMA_VERSION >= 97
        assert _snapshot(conn) == before
        assert NEW_CONSENT_CHECK in _stored_sql(conn)
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        conn.execute("UPDATE installed_items SET consent_via = ? WHERE install_id = 'i0'", (CONSENT_PACK,))
        assert conn.execute("SELECT consent_via FROM installed_items WHERE install_id = 'i0'").fetchone()[0] == "pack"
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE installed_items SET consent_via = 'forged' WHERE install_id = 'i1'")


def test_a_second_run_changes_nothing(v96_state):
    assert ensure_db_migrated(v96_state).status == "ok"
    with _open(db_path_for(v96_state)) as conn:
        sql, snap = _stored_sql(conn), _snapshot(conn)
        assert widen_consent_check(conn) is False
        assert _stored_sql(conn) == sql and _snapshot(conn) == snap
    assert ensure_db_migrated(v96_state).status == "ok"


def test_an_unrecognised_stored_check_refuses_rather_than_guessing(v96_state):
    with _open(db_path_for(v96_state)) as conn:
        conn.execute("PRAGMA writable_schema=ON")
        conn.execute("UPDATE sqlite_master SET sql = ? WHERE name = 'installed_items'", (_stored_sql(conn).replace(OLD_CONSENT_CHECK, ""),))
        conn.execute("PRAGMA writable_schema=RESET")
        with pytest.raises(RuntimeError):
            widen_consent_check(conn)


def test_the_by_reference_installer_records_pack():
    assert install_by_reference.CONSENT_PACK == CONSENT_PACK == "pack"
    assert not hasattr(install_by_reference, "CONSENT_ONE_CLICK")
