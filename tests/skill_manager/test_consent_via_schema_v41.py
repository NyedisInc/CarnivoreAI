
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Dict, List

import pytest

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from src.core import db_models
from src.core.db import connect, db_path_for, get_schema_version, set_meta
from src.core.db_migration import ensure_db_migrated
from src.core.db_schema_audit import (
    AUDIT_MISSING,
    AUDIT_OK,
    UNGATED_VERSION_COLUMNS,
    audit_schema,
    repair_missing,
)
from src.core.db_steps import STEPS
from src.core.skills.consent_via_ddl import (
    CONSENT_VIA_COLUMN,
    CONSENT_VIA_VALUES,
    REVERSAL_SQL_V41,
    V41_COLUMNS,
)

STAMP = "2026-09-20T10:00:00.000000Z"


def _open(path: Path):
    return closing(connect(path, create=False))


def _rewind_to_v40(state_dir: Path) -> None:
    with _open(db_path_for(state_dir)) as conn:
        conn.execute("ALTER TABLE installed_items DROP COLUMN forked")
        conn.execute("ALTER TABLE installed_items DROP COLUMN consent_via")
        set_meta(conn, db_models.META_SCHEMA_VERSION, "40")


def _seed_rows(path: Path) -> None:
    with _open(path) as conn:
        for n, (scope, project) in enumerate((("global", ""), ("project", "/work/api"))):
            conn.execute(
                "INSERT INTO installed_items (install_id, item_id, kind, publisher, name, version, "
                "digest, scope, project_path, auto_update, source_index_url, consented_digest, "
                "consented_body_sha, publisher_key_id, revision, installed_at, updated_at) "
                "VALUES (?, ?, 'skill', 'acme', ?, '1.0.0', ?, ?, ?, 0, 'https://x.invalid/i.json', "
                "?, ?, 'RWkey', 1, ?, ?)",
                (f"i{n}", f"acme/s{n}", f"s{n}", "d" * 64, scope, project, "d" * 64, "b" * 64,
                 STAMP, STAMP))


def _dump(conn) -> List[Dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM installed_items ORDER BY install_id")]


@pytest.fixture()
def v40_state(tmp_path) -> Path:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    assert ensure_db_migrated(state_dir).status == "ok"
    _rewind_to_v40(state_dir)
    _seed_rows(db_path_for(state_dir))
    return state_dir


def test_the_rewind_really_is_v40(v40_state):
    with _open(db_path_for(v40_state)) as conn:
        assert get_schema_version(conn) == 40
        assert CONSENT_VIA_COLUMN not in {r[1] for r in conn.execute("PRAGMA table_info(installed_items)")}
        assert conn.execute("SELECT COUNT(*) FROM installed_items").fetchone()[0] == 2


def test_a_real_shaped_v40_datastore_upgrades_and_every_row_reads_sheet(v40_state):
    path = db_path_for(v40_state)
    with _open(path) as conn:
        before = _dump(conn)
    state = ensure_db_migrated(v40_state)
    assert state.status == "ok", state.message
    with _open(path) as conn:
        assert get_schema_version(conn) == db_models.CURRENT_SCHEMA_VERSION >= 41
        after = _dump(conn)
        trail = conn.execute(
            "SELECT status, backup_path, backup_verified FROM migration_trail "
            "WHERE from_version = '40'").fetchall()
    assert [r[CONSENT_VIA_COLUMN] for r in after] == ["sheet", "sheet"]
    assert [{k: v for k, v in r.items() if k not in (CONSENT_VIA_COLUMN, 'forked')} for r in after] == before
    status, backup_path, verified = trail[-1]
    assert status.startswith("completed") and verified == 1 and "bak-v40" in backup_path
    assert list(v40_state.rglob(backup_path)), "the recorded backup is not on disk"


def test_the_column_refuses_a_value_outside_the_closed_list(v40_state):
    assert ensure_db_migrated(v40_state).status == "ok"
    with _open(db_path_for(v40_state)) as conn:
        for value in CONSENT_VIA_VALUES:
            conn.execute("UPDATE installed_items SET consent_via = ? WHERE install_id = 'i0'", (value,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE installed_items SET consent_via = 'whatever' WHERE install_id = 'i0'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE installed_items SET consent_via = NULL WHERE install_id = 'i0'")


def test_the_step_is_idempotent_and_skips_a_missing_table():
    bare = sqlite3.connect(":memory:")
    bare.execute("BEGIN")
    STEPS[40](bare)
    conn = sqlite3.connect(":memory:")
    conn.execute("BEGIN")
    for version in range(0, 40):
        STEPS[version](conn)
    STEPS[40](conn)
    STEPS[40](conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(installed_items)")]
    assert cols.count(CONSENT_VIA_COLUMN) == 1


def test_the_step_is_audited_and_its_reversal_declared():
    assert UNGATED_VERSION_COLUMNS[41] == V41_COLUMNS
    assert db_models.REVERSAL_SQL_V41 == REVERSAL_SQL_V41 == ()
    assert db_models.REVERSAL_DESTROYS[41] == ("installed_items.consent_via",)


def _chain(skip=()) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("BEGIN")
    for version in range(0, db_models.CURRENT_SCHEMA_VERSION):
        if version not in skip:
            STEPS[version](conn)
    conn.commit()
    return conn


def test_a_healthy_chain_audits_clean_and_a_crossed_key_40_is_repaired():
    assert audit_schema(_chain(), db_models.CURRENT_SCHEMA_VERSION).status == AUDIT_OK
    conn = _chain(skip=(40,))
    audit = audit_schema(conn, db_models.CURRENT_SCHEMA_VERSION)
    assert audit.status == AUDIT_MISSING
    assert "installed_items.consent_via" in set(audit.missing_names)
    conn.execute("BEGIN")
    repair_missing(conn, audit.missing)
    conn.commit()
    assert audit_schema(conn, db_models.CURRENT_SCHEMA_VERSION).status == AUDIT_OK
