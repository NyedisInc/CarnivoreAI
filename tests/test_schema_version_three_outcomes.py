
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import List

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import (
    SCHEMA_VERSION_ABSENT,
    SCHEMA_VERSION_PARSED,
    SCHEMA_VERSION_UNREADABLE,
    connect,
    database_is_populated,
    db_path_for,
    get_schema_version,
    read_schema_version,
)
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db_state import (
    STATUS_DEGRADED_SCHEMA_VERSION_UNREADABLE,
    STATUS_OK,
    READONLY_STATUSES,
)

UNPARSEABLE = ("", "3-dirty", "v1", "1.0", "one", "  ", "1,0")

PARSEABLE = ((" 1 ", 1), ("01", 1), ("+1", 1), ("1\n", 1), ("2", 2))


def _make_v1_populated(state_dir: Path, version_value: str = "1") -> Path:
    db = db_path_for(state_dir)
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT, path TEXT)"
    )
    conn.execute(
        "CREATE TABLE migration_trail (entry_uuid TEXT PRIMARY KEY, payload TEXT)"
    )
    for i in range(9):
        conn.execute(
            "INSERT INTO projects (name, path) VALUES (?, ?)",
            (f"project{i}", f"/tmp/project{i}"),
        )
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
        (version_value,),
    )
    conn.commit()
    conn.close()
    return db




@pytest.mark.parametrize("raw", UNPARSEABLE)
def test_unparseable_version_is_its_own_outcome(tmp_path: Path, raw: str) -> None:
    _make_v1_populated(tmp_path, raw)
    conn = connect(db_path_for(tmp_path))
    try:
        read = read_schema_version(conn)
        assert read.outcome == SCHEMA_VERSION_UNREADABLE, raw
        assert read.value is None, "there is no number to report"
        assert read.readable is False
        assert read.raw == raw, "the operator must be shown what was found"
    finally:
        conn.close()


@pytest.mark.parametrize("raw,expected", PARSEABLE)
def test_parseable_versions_still_parse(
    tmp_path: Path, raw: str, expected: int
) -> None:
    _make_v1_populated(tmp_path, raw)
    conn = connect(db_path_for(tmp_path))
    try:
        read = read_schema_version(conn)
        assert read.outcome == SCHEMA_VERSION_PARSED, repr(raw)
        assert read.value == expected
    finally:
        conn.close()


def test_absent_version_is_distinct_from_unreadable(tmp_path: Path) -> None:
    db = _make_v1_populated(tmp_path)
    conn = sqlite3.connect(str(db))
    conn.execute("DELETE FROM meta WHERE key='schema_version'")
    conn.commit()
    conn.close()

    conn = connect(db_path_for(tmp_path))
    try:
        read = read_schema_version(conn)
        assert read.outcome == SCHEMA_VERSION_ABSENT
        assert read.value is None
        assert read.readable is True, "absent IS an answer; unreadable is not"
    finally:
        conn.close()


@pytest.mark.parametrize("raw", UNPARSEABLE)
def test_unparseable_version_never_migrates_without_a_backup(
    tmp_path: Path, raw: str
) -> None:
    _make_v1_populated(tmp_path, raw)

    state = ensure_db_migrated(tmp_path, config_version=4, app_version="0.0.0")

    assert state.status == STATUS_DEGRADED_SCHEMA_VERSION_UNREADABLE
    assert state.status in READONLY_STATUSES, (
        "a database whose shape we cannot establish must not be written to"
    )
    assert state.readonly is True
    assert state.migrations_paused is True

    conn = sqlite3.connect(str(db_path_for(tmp_path)))
    try:
        stored = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        assert stored[0] == raw, "the value must be left exactly as found"
        projects = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        assert projects == 9, "the user's data must be untouched"
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "sessions" not in tables, "no migration may have run"
    finally:
        conn.close()


def test_absent_version_on_a_populated_database_does_not_bootstrap(
    tmp_path: Path,
) -> None:
    db = _make_v1_populated(tmp_path)
    conn = sqlite3.connect(str(db))
    conn.execute("DELETE FROM meta WHERE key='schema_version'")
    conn.commit()
    conn.close()

    state = ensure_db_migrated(tmp_path, config_version=4, app_version="0.0.0")

    assert state.status == STATUS_DEGRADED_SCHEMA_VERSION_UNREADABLE
    conn = sqlite3.connect(str(db_path_for(tmp_path)))
    try:
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 9
    finally:
        conn.close()


def test_populated_probe_reports_three_outcomes(tmp_path: Path) -> None:
    _make_v1_populated(tmp_path)
    conn = connect(db_path_for(tmp_path))
    try:
        assert database_is_populated(conn) is True
    finally:
        conn.close()

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    db = db_path_for(empty_dir)
    raw = sqlite3.connect(str(db))
    raw.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    raw.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT)")
    raw.commit()
    raw.close()
    conn = connect(db)
    try:
        assert database_is_populated(conn) is False, (
            "an existing but empty projects table is a real answer of no"
        )
    finally:
        conn.close()

    no_table = tmp_path / "notable"
    no_table.mkdir()
    db2 = db_path_for(no_table)
    raw = sqlite3.connect(str(db2))
    raw.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    raw.commit()
    raw.close()
    conn = connect(db2)
    try:
        assert database_is_populated(conn) is False, (
            "a file with no projects table genuinely has no projects"
        )
    finally:
        conn.close()


@pytest.mark.parametrize("raw", UNPARSEABLE)
def test_unparseable_version_pauses_even_on_an_empty_database(
    tmp_path: Path, raw: str
) -> None:
    db = db_path_for(tmp_path)
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?)", (raw,)
    )
    conn.commit()
    conn.close()

    state = ensure_db_migrated(tmp_path, config_version=4, app_version="0.0.0")

    assert state.status == STATUS_DEGRADED_SCHEMA_VERSION_UNREADABLE, (
        "an unreadable version is unreadable whether or not the file "
        "happens to be empty"
    )

    conn = sqlite3.connect(str(db))
    try:
        stored = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        assert stored[0] == raw, "nothing may be rewritten"
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "sessions" not in tables
    finally:
        conn.close()


def test_unanswerable_populated_probe_is_treated_like_populated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _make_v1_populated(tmp_path)
    conn = sqlite3.connect(str(db))
    conn.execute("DELETE FROM meta WHERE key='schema_version'")
    conn.commit()
    conn.close()

    import src.core.db_version_gate as gate

    monkeypatch.setattr(gate, "database_is_populated", lambda conn: None)

    state = ensure_db_migrated(tmp_path, config_version=4, app_version="0.0.0")

    assert state.status == STATUS_DEGRADED_SCHEMA_VERSION_UNREADABLE, (
        "a probe that could not answer must not authorise the "
        "fresh-install path"
    )
    assert "CANNOT_DETERMINE" in (state.detail or ""), (
        "the message must say the probe could not answer, not invent one"
    )


def test_get_schema_version_is_documented_as_report_only() -> None:
    doc = get_schema_version.__doc__ or ""
    assert "DO NOT USE THIS AS A GATE" in doc
    assert "read_schema_version" in doc


def test_real_v1_database_still_migrates_cleanly(tmp_path: Path) -> None:
    _make_v1_populated(tmp_path, "1")

    state = ensure_db_migrated(tmp_path, config_version=4, app_version="0.0.0")

    assert state.status == STATUS_OK
    assert state.schema_version == CURRENT_SCHEMA_VERSION
    assert state.migrations_applied == [
        f"{v}->{v + 1}" for v in range(1, CURRENT_SCHEMA_VERSION)
    ]
    assert state.backup_path, "a populated migration must take a backup"
    backups = list(tmp_path.glob("*.bak-*"))
    assert len(backups) == 1

    conn = sqlite3.connect(str(db_path_for(tmp_path)))
    try:
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 9
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()




def _trail_lines(state_dir: Path) -> List[dict]:
    path = state_dir / "migration_trail.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def test_retry_after_a_clean_failure_claims_no_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_v1_populated(tmp_path, "1")

    import src.core.db_migration as dbmig

    def _boom(*args, **kwargs):
        raise sqlite3.OperationalError("INJECTED: first attempt fails cleanly")

    monkeypatch.setattr(dbmig, "run_chain", _boom)
    first = ensure_db_migrated(tmp_path, config_version=4, app_version="0.0.0")
    assert first.status != STATUS_OK, "the first attempt must have failed"

    closing = [e for e in _trail_lines(tmp_path) if e.get("status") == "failed"]
    assert closing, "the failed attempt must have CLOSED its trail entry"

    monkeypatch.undo()
    second = ensure_db_migrated(tmp_path, config_version=4, app_version="0.0.0")
    assert second.status == STATUS_OK

    statuses = [e.get("status") for e in _trail_lines(tmp_path)]
    assert "completed_after_interrupt" not in statuses, (
        "no attempt was ever interrupted - one failed cleanly and was "
        f"recorded as such. Trail statuses: {statuses}"
    )
    assert "completed" in statuses


def test_retry_after_a_real_interrupt_still_reports_it(tmp_path: Path) -> None:
    _make_v1_populated(tmp_path, "1")

    trail = tmp_path / "migration_trail.jsonl"
    trail.write_text(
        json.dumps(
            {
                "entry_uuid": "interrupted-uuid-0001",
                "kind": "schema",
                "from_version": "1",
                "to_version": str(CURRENT_SCHEMA_VERSION),
                "status": "started",
                "started_at": "2026-01-01T00:00:00Z",
                "completed_at": None,
                "backup_path": None,
                "backup_verified": None,
                "app_version": "0.0.0",
                "error": None,
                "detail": "INJECTED: an attempt that died before closing",
            }
        )
        + "\n"
    )

    state = ensure_db_migrated(tmp_path, config_version=4, app_version="0.0.0")
    assert state.status == STATUS_OK

    statuses = [e.get("status") for e in _trail_lines(tmp_path)]
    assert "completed_after_interrupt" in statuses, (
        "an unclosed started line IS an interrupt and must still be named"
    )
