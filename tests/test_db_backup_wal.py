
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
from contextlib import closing
from pathlib import Path

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_wal_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_wal_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.db_models import CURRENT_SCHEMA_VERSION
from src.core.db import connect, db_path_for, get_schema_version
from src.core.db_backup import take_backup, verify_backup
from src.core.db_migration import ensure_db_migrated

ROW_COUNT = 7


def _dirty_the_wal(state_dir: Path, rows: int) -> None:
    script = textwrap.dedent(
        f"""
        import os, sqlite3
        conn = sqlite3.connect({str(db_path_for(state_dir))!r}, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("BEGIN IMMEDIATE")
        for i in range({rows}):
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?)",
                (f"wal_row_{{i}}", str(i)),
            )
        conn.execute("COMMIT")
        # No conn.close(), no interpreter shutdown: nothing checkpoints.
        os._exit(0)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, (
        f"WAL-dirtying child failed: {result.stdout!r} {result.stderr!r}"
    )


def _count_meta_rows(db_file: Path) -> int:
    try:
        with closing(sqlite3.connect(str(db_file))) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM meta").fetchone()[0])
    except sqlite3.Error:
        return -1


def test_vacuum_into_captures_wal_commits_and_cp_does_not(tmp_path) -> None:
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    live = db_path_for(tmp_path)
    baseline = _count_meta_rows(live)

    _dirty_the_wal(tmp_path, ROW_COUNT)

    wal_file = Path(str(live) + "-wal")
    assert wal_file.exists() and wal_file.stat().st_size > 0, (
        "the child checkpointed after all - with an empty WAL, cp and "
        "VACUUM INTO agree and this test proves nothing"
    )

    expected = baseline + ROW_COUNT

    cp_dir = tmp_path / "cp_copy"
    cp_dir.mkdir()
    cp_target = cp_dir / "cloude.db"
    shutil.copy2(live, cp_target)
    cp_count = _count_meta_rows(cp_target)

    result = take_backup(live, tmp_path, CURRENT_SCHEMA_VERSION)
    assert result.verified is True, result.reason
    vacuum_count = _count_meta_rows(result.path)

    verified, reason = verify_backup(result.path, CURRENT_SCHEMA_VERSION)
    assert verified is True, reason
    with closing(connect(result.path, create=False)) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert get_schema_version(conn) == CURRENT_SCHEMA_VERSION

    assert vacuum_count != cp_count, (
        f"cp and VACUUM INTO produced the same row count ({cp_count}); this "
        "test cannot distinguish them, so it is not measuring what it claims"
    )
    assert vacuum_count == expected, (
        f"VACUUM INTO lost commits: expected {expected}, got {vacuum_count}"
    )
    assert cp_count < expected, (
        f"cp captured {cp_count} of {expected} rows - it was supposed to "
        "silently lose the uncheckpointed ones"
    )
    assert cp_count >= 0, "the cp copy did not even open - it opens CLEANLY and lies"


def test_backup_verification_rejects_a_wrong_version_snapshot(tmp_path) -> None:
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    result = take_backup(db_path_for(tmp_path), tmp_path, CURRENT_SCHEMA_VERSION)
    assert result.verified is True

    verified, reason = verify_backup(result.path, 99)
    assert verified is False
    assert (
        f"records schema_version {CURRENT_SCHEMA_VERSION}, expected 99"
        in reason
    )


def test_unverifiable_backup_is_deleted_not_left_behind(tmp_path) -> None:
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    result = take_backup(db_path_for(tmp_path), tmp_path, 99)
    assert result.taken is True
    assert result.verified is False
    assert result.path is not None
    assert not result.path.exists()


def test_backup_of_a_missing_database_is_reported_not_invented(tmp_path) -> None:
    result = take_backup(tmp_path / "cloude.db", tmp_path, 1)
    assert result.taken is False
    assert result.verified is False
    assert "nothing to back up" in result.reason
    assert not list(tmp_path.glob("cloude.db.bak-*"))


def test_verification_rejects_a_corrupt_copy_whose_version_still_reads(
    tmp_path,
) -> None:
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    result = take_backup(db_path_for(tmp_path), tmp_path, CURRENT_SCHEMA_VERSION)
    assert result.verified is True

    with closing(sqlite3.connect(str(result.path), isolation_level=None)) as conn:
        conn.execute("CREATE TABLE bulk (id INTEGER PRIMARY KEY, blob TEXT)")
        conn.executemany(
            "INSERT INTO bulk (blob) VALUES (?)", [("x" * 400,)] * 400
        )
    size = result.path.stat().st_size
    with open(result.path, "r+b") as handle:
        handle.seek(size - 2000)
        handle.write(b"\x00\xff" * 400)

    with closing(sqlite3.connect(str(result.path))) as conn:
        assert (
            conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()[0]
            == str(CURRENT_SCHEMA_VERSION)
        )

    verified, reason = verify_backup(result.path, CURRENT_SCHEMA_VERSION)
    assert verified is False
    assert "integrity_check" in reason
