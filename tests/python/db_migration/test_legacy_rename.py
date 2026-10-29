
from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import structlog

from src.core import db
from src.core.db_rename.legacy import (
    OUTCOME_CONFLICT,
    OUTCOME_DEFERRED,
    OUTCOME_EMPTY_REMOVED,
    OUTCOME_NOTHING,
    OUTCOME_RENAMED,
    legacy_fallback_for,
    migrate_legacy_db,
)

ROOT = Path(__file__).resolve().parents[3]


def _make_db(path: Path, rows: int = 5) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO meta VALUES ('schema_version', '1')")
    conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT)")
    for i in range(rows):
        conn.execute("INSERT INTO projects (name) VALUES (?)", (f"p{i}",))
    return conn


def _count(path: Path) -> int:
    with sqlite3.connect(str(path)) as conn:
        return conn.execute("SELECT count(*) FROM projects").fetchone()[0]


@pytest.fixture(autouse=True)
def _clean_fallback():
    yield
    from src.core.db_rename import legacy as db_legacy_rename

    db_legacy_rename._FALLBACK.clear()


def test_only_carnivore_is_a_no_op(tmp_path: Path) -> None:
    _make_db(tmp_path / "carnivore.db").close()
    assert migrate_legacy_db(tmp_path).outcome == OUTCOME_NOTHING
    assert db.db_path_for(tmp_path) == tmp_path / "carnivore.db"


def test_legacy_with_wal_is_renamed_with_all_rows(tmp_path: Path) -> None:
    src, state = tmp_path / "src", tmp_path / "state"
    src.mkdir()
    state.mkdir()
    writer = _make_db(src / "cloude.db", rows=7)
    shutil.copy(src / "cloude.db", state / "cloude.db")
    shutil.copy(src / "cloude.db-wal", state / "cloude.db-wal")
    writer.close()
    legacy = state / "cloude.db"
    assert (state / "cloude.db-wal").stat().st_size > 0
    assert sqlite3.connect(f"file:{legacy}?mode=ro&immutable=1", uri=True).execute(
        "SELECT count(*) FROM sqlite_master").fetchone()[0] == 0, "rows must live only in the WAL"

    outcome = migrate_legacy_db(state)

    assert outcome.outcome == OUTCOME_RENAMED, outcome
    assert not legacy.exists()
    assert not (state / "cloude.db-wal").exists()
    assert not (state / "cloude.db-shm").exists()
    assert _count(state / "carnivore.db") == 7
    assert db.db_path_for(state) == state / "carnivore.db"
    assert list(state.glob("carnivore.db.bak-v1-*.nobackup")), "the pre-rename backup must exist"
    assert migrate_legacy_db(state).outcome == OUTCOME_NOTHING


def test_empty_legacy_is_deleted(tmp_path: Path) -> None:
    _make_db(tmp_path / "carnivore.db").close()
    (tmp_path / "cloude.db").write_bytes(b"")
    sqlite3.connect(str(tmp_path / "other.db")).close()
    assert migrate_legacy_db(tmp_path).outcome == OUTCOME_EMPTY_REMOVED
    assert not (tmp_path / "cloude.db").exists()
    assert _count(tmp_path / "carnivore.db") == 5


def test_table_less_sqlite_legacy_is_deleted(tmp_path: Path) -> None:
    sqlite3.connect(str(tmp_path / "cloude.db")).close()
    conn = sqlite3.connect(str(tmp_path / "cloude.db"))
    conn.execute("PRAGMA user_version=1")
    conn.commit()
    conn.close()
    assert migrate_legacy_db(tmp_path).outcome == OUTCOME_EMPTY_REMOVED
    assert not (tmp_path / "cloude.db").exists()


def test_both_with_data_touches_neither_uses_carnivore_and_logs_error(tmp_path: Path) -> None:
    _make_db(tmp_path / "carnivore.db", rows=2).close()
    _make_db(tmp_path / "cloude.db", rows=9).close()
    with structlog.testing.capture_logs() as logs:
        outcome = migrate_legacy_db(tmp_path)
    assert outcome.outcome == OUTCOME_CONFLICT
    assert _count(tmp_path / "carnivore.db") == 2 and _count(tmp_path / "cloude.db") == 9
    assert any(r["event"] == "legacy_db_conflict" and r["log_level"] == "error" for r in logs)
    assert db.db_path_for(tmp_path) == tmp_path / "carnivore.db"
    assert legacy_fallback_for(tmp_path) is None


def test_corrupt_legacy_defers_and_boot_continues(tmp_path: Path) -> None:
    (tmp_path / "cloude.db").write_bytes(b"this is definitely not a sqlite file" * 40)
    outcome = migrate_legacy_db(tmp_path)
    assert outcome.outcome == OUTCOME_DEFERRED
    assert (tmp_path / "cloude.db").exists() and not (tmp_path / "carnivore.db").exists()
    assert db.db_path_for(tmp_path) == tmp_path / "cloude.db"


def test_failed_backup_defers(tmp_path: Path, monkeypatch) -> None:
    from src.core.db_rename import legacy as mod

    _make_db(tmp_path / "cloude.db").close()
    monkeypatch.setattr(mod, "_backup_first", lambda legacy, state_dir: "backup not verified")
    assert migrate_legacy_db(tmp_path).outcome == OUTCOME_DEFERRED
    assert (tmp_path / "cloude.db").exists() and not (tmp_path / "carnivore.db").exists()


def test_concurrent_migrator_never_overwrites_the_renamed_database(tmp_path: Path, monkeypatch) -> None:
    from src.core.db_rename import legacy as mod

    _make_db(tmp_path / "cloude.db", rows=6).close()
    real_backup = mod._backup_first

    def backup_then_other_finishes(legacy: Path, state_dir: Path):
        reason = real_backup(legacy, state_dir)
        code = (
            f"import sys; sys.path.insert(0, {str(ROOT)!r}); from pathlib import Path; "
            f"from src.core.db_rename.legacy import migrate_legacy_db; "
            f"print(migrate_legacy_db(Path({str(tmp_path)!r})).outcome)"
        )
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
        assert OUTCOME_RENAMED in out.stdout, out.stderr[-500:]
        return reason

    monkeypatch.setattr(mod, "_backup_first", backup_then_other_finishes)
    assert migrate_legacy_db(tmp_path).outcome == OUTCOME_DEFERRED
    assert _count(tmp_path / "carnivore.db") == 6
    assert not (tmp_path / "cloude.db").exists(), "a missing legacy file must never be re-created"


def test_deferred_boot_takes_no_backup(tmp_path: Path) -> None:
    legacy = tmp_path / "cloude.db"
    _make_db(legacy).close()
    reader = sqlite3.connect(str(legacy))
    reader.execute("SELECT count(*) FROM projects").fetchone()
    try:
        assert migrate_legacy_db(tmp_path).outcome == OUTCOME_DEFERRED
    finally:
        reader.close()
    assert not list(tmp_path.glob("*.nobackup"))


def test_readable_db_path_never_creates(tmp_path: Path) -> None:
    from src.core.db_rename.legacy import readable_db_path

    assert readable_db_path(tmp_path) == tmp_path / "carnivore.db"
    _make_db(tmp_path / "cloude.db").close()
    assert readable_db_path(tmp_path) == tmp_path / "cloude.db"
    _make_db(tmp_path / "carnivore.db").close()
    assert readable_db_path(tmp_path) == tmp_path / "carnivore.db"
    assert not (tmp_path / "other").exists()


def test_open_writer_blocks_the_rename(tmp_path: Path) -> None:
    legacy = tmp_path / "cloude.db"
    _make_db(legacy).close()
    holder = sqlite3.connect(str(legacy), isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    holder.execute("INSERT INTO projects (name) VALUES ('in flight')")
    try:
        with structlog.testing.capture_logs() as logs:
            outcome = migrate_legacy_db(tmp_path)
        assert outcome.outcome == OUTCOME_DEFERRED
        assert legacy.exists() and not (tmp_path / "carnivore.db").exists()
        assert any(r["event"] == "legacy_db_rename_deferred" for r in logs)
        assert db.db_path_for(tmp_path) == legacy
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert migrate_legacy_db(tmp_path).outcome == OUTCOME_RENAMED
    assert db.db_path_for(tmp_path) == tmp_path / "carnivore.db"


def test_idle_open_connection_also_blocks_the_rename(tmp_path: Path) -> None:
    legacy = tmp_path / "cloude.db"
    _make_db(legacy).close()
    reader = sqlite3.connect(str(legacy))
    reader.execute("SELECT count(*) FROM projects").fetchone()
    try:
        assert migrate_legacy_db(tmp_path).outcome == OUTCOME_DEFERRED
        assert legacy.exists() and not (tmp_path / "carnivore.db").exists()
    finally:
        reader.close()


def test_empty_carnivore_shell_beside_real_legacy_is_replaced(tmp_path: Path) -> None:
    (tmp_path / "carnivore.db").write_bytes(b"")
    _make_db(tmp_path / "cloude.db", rows=4).close()
    assert migrate_legacy_db(tmp_path).outcome == OUTCOME_RENAMED
    assert _count(tmp_path / "carnivore.db") == 4


def test_orphan_legacy_sidecars_are_swept(tmp_path: Path) -> None:
    _make_db(tmp_path / "carnivore.db").close()
    (tmp_path / "cloude.db-wal").write_bytes(b"x")
    migrate_legacy_db(tmp_path)
    assert not (tmp_path / "cloude.db-wal").exists()


def test_deploy_backup_never_creates_a_missing_database(tmp_path: Path) -> None:
    text = (ROOT / "scripts" / "deploy-dmg.sh").read_text()
    start = text.index("backup_database() {")
    func = text[start : text.index("\n}\n", start) + 3]
    state, backup = tmp_path / "state", tmp_path / "bk"
    state.mkdir()
    script = f'log() {{ :; }}\nSTATE="{state}"\nBACKUP_DIR="{backup}"\n{func}\nbackup_database\n'
    subprocess.run(["bash", "-c", script], check=True)
    assert list(state.iterdir()) == []
    _make_db(state / "carnivore.db").close()
    subprocess.run(["bash", "-c", script], check=True)
    assert {p.name for p in state.iterdir()} <= {"carnivore.db", "carnivore.db-wal", "carnivore.db-shm"}
    assert (backup / "carnivore.db").exists()


def test_empty_carnivore_shell_plus_blocked_lock_keeps_the_real_legacy_file(tmp_path: Path) -> None:
    (tmp_path / "carnivore.db").write_bytes(b"")
    legacy = tmp_path / "cloude.db"
    _make_db(legacy, rows=3).close()
    reader = sqlite3.connect(str(legacy))
    reader.execute("SELECT count(*) FROM projects").fetchone()
    try:
        assert migrate_legacy_db(tmp_path).outcome == OUTCOME_DEFERRED
        assert db.db_path_for(tmp_path) == legacy
    finally:
        reader.close()
