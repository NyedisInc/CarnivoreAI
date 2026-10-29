
from __future__ import annotations

import sqlite3

import pytest

from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_schema_audit import (
    AUDIT_CANNOT_DETERMINE,
    AUDIT_MISSING,
    AUDIT_OK,
    SUPERSEDED_OBJECTS,
    audit_schema,
    declared_objects,
    repair_missing,
)
from src.core.db_steps import STEPS

CATALOG_TABLES = (
    "installed_items",
    "installed_item_targets",
    "catalog_revocations_seen",
    "catalog_index_state",
    "installed_loadout_members",
)

RESERVED_KEYS = (26, 27, 28)

CROSSED_NAMES = CATALOG_TABLES + ("installed_items.consent_via", "installed_items.forked")


def _chain_with_reservations(conn: sqlite3.Connection, keys) -> None:
    skip = set(keys)
    conn.execute("BEGIN")
    for version in range(0, CURRENT_SCHEMA_VERSION):
        if version in skip:
            continue
        STEPS[version](conn)
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES "
        "('schema_version', ?)",
        (str(CURRENT_SCHEMA_VERSION),),
    )
    conn.commit()


@pytest.fixture()
def healthy_db(tmp_path):
    conn = sqlite3.connect(tmp_path / "healthy.db")
    _chain_with_reservations(conn, ())
    yield conn
    conn.close()


@pytest.fixture()
def crossed_reservations_db(tmp_path):
    conn = sqlite3.connect(tmp_path / "crossed.db")
    _chain_with_reservations(conn, RESERVED_KEYS)
    yield conn
    conn.close()


def test_a_database_that_crossed_the_reservations_is_caught(
    crossed_reservations_db,
):
    audit = audit_schema(crossed_reservations_db, CURRENT_SCHEMA_VERSION)
    assert audit.status == AUDIT_MISSING
    assert set(audit.missing_names) == set(CROSSED_NAMES)


def test_the_catalog_tables_really_are_absent_first(
    crossed_reservations_db,
):
    present = {
        row[0]
        for row in crossed_reservations_db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    for table in CATALOG_TABLES:
        assert table not in present
    version = crossed_reservations_db.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()[0]
    assert int(version) == CURRENT_SCHEMA_VERSION


def test_repair_creates_exactly_what_was_missing(crossed_reservations_db):
    audit = audit_schema(crossed_reservations_db, CURRENT_SCHEMA_VERSION)
    crossed_reservations_db.execute("BEGIN")
    created = repair_missing(crossed_reservations_db, audit.missing)
    crossed_reservations_db.commit()

    assert set(created) == set(CROSSED_NAMES)
    after = audit_schema(crossed_reservations_db, CURRENT_SCHEMA_VERSION)
    assert after.status == AUDIT_OK


def test_repaired_schema_is_identical_to_one_that_never_skipped(
    crossed_reservations_db, healthy_db
):
    audit = audit_schema(crossed_reservations_db, CURRENT_SCHEMA_VERSION)
    crossed_reservations_db.execute("BEGIN")
    repair_missing(crossed_reservations_db, audit.missing)
    crossed_reservations_db.commit()

    for table in CATALOG_TABLES:
        repaired = crossed_reservations_db.execute(
            "SELECT sql FROM sqlite_master WHERE name = ?", (table,)
        ).fetchone()[0]
        normal = healthy_db.execute(
            "SELECT sql FROM sqlite_master WHERE name = ?", (table,)
        ).fetchone()[0]
        assert repaired == normal


def test_the_repair_leaves_the_version_alone(crossed_reservations_db):
    audit = audit_schema(crossed_reservations_db, CURRENT_SCHEMA_VERSION)
    crossed_reservations_db.execute("BEGIN")
    repair_missing(crossed_reservations_db, audit.missing)
    crossed_reservations_db.commit()
    version = crossed_reservations_db.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()[0]
    assert int(version) == CURRENT_SCHEMA_VERSION


def test_the_repair_is_idempotent(crossed_reservations_db):
    audit = audit_schema(crossed_reservations_db, CURRENT_SCHEMA_VERSION)
    crossed_reservations_db.execute("BEGIN")
    repair_missing(crossed_reservations_db, audit.missing)
    repair_missing(crossed_reservations_db, audit.missing)
    crossed_reservations_db.commit()
    assert audit_schema(
        crossed_reservations_db, CURRENT_SCHEMA_VERSION
    ).status == AUDIT_OK




def test_a_healthy_database_is_not_accused(healthy_db):
    audit = audit_schema(healthy_db, CURRENT_SCHEMA_VERSION)
    assert audit.status == AUDIT_OK
    assert audit.missing == []
    assert audit.checked > 0


def test_a_relocated_archive_is_not_reported_missing(healthy_db):
    healthy_db.execute("PRAGMA foreign_keys = OFF")
    healthy_db.execute("BEGIN")
    for name in (
        "transcript_records",
        "transcript_root_decisions",
        "transcript_archives",
        "archive_project_overlay",
    ):
        healthy_db.execute(f"DROP TABLE IF EXISTS {name}")
    healthy_db.commit()

    audit = audit_schema(healthy_db, CURRENT_SCHEMA_VERSION)
    assert audit.status == AUDIT_OK
    assert audit.skipped_archive > 0


def test_a_superseded_index_is_never_demanded_back(healthy_db):
    assert "ix_sessions_claude_uuid" in SUPERSEDED_OBJECTS
    names = {obj.name for obj in declared_objects(CURRENT_SCHEMA_VERSION)}
    assert "ix_sessions_claude_uuid" not in names
    assert audit_schema(healthy_db, CURRENT_SCHEMA_VERSION).status == AUDIT_OK


def test_an_unreadable_schema_refuses_rather_than_passing(tmp_path):

    class Broken:

        def execute(self, *args, **kwargs):
            raise sqlite3.DatabaseError("file is not a database")

    audit = audit_schema(Broken(), CURRENT_SCHEMA_VERSION)
    assert audit.status == AUDIT_CANNOT_DETERMINE
    assert audit.missing == []


def test_an_older_version_is_not_held_to_a_newer_one_s_objects():
    names = {obj.name for obj in declared_objects(26)}
    for table in CATALOG_TABLES:
        assert table not in names
    later = {obj.name for obj in declared_objects(CURRENT_SCHEMA_VERSION)}
    for table in CATALOG_TABLES:
        assert table in later
