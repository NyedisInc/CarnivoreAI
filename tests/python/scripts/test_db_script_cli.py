"""Behavior of the one-off database scripts' command lines (wave G slice M2: u024-08, u024-09, u024-10, u024-11).

Every test uses a temp directory; nothing here touches a real database.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

from scripts import backfill_claude_session_uuid as backfill
from scripts import classify_session_kind as classify
from scripts import import_transcript_sessions as importer
from src.core.db_rename import legacy


@pytest.fixture()
def no_default_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a machine with no local install: script_default_db exits."""

    def _exit() -> str:
        raise SystemExit("no database found")

    monkeypatch.setattr(legacy, "script_default_db", _exit)
    for module in (backfill, classify, importer):
        monkeypatch.setattr(module, "resolve_script_db", legacy.resolve_script_db)


@pytest.mark.parametrize("build", [backfill.build_parser, classify.build_parser, importer.build_parser])
def test_building_the_parser_never_needs_a_local_database(no_default_db: None, build) -> None:
    """u024-08: argparse defaults must not resolve the default database."""
    assert build().parse_args([]).db is None


def test_facts_mode_runs_without_any_local_database(no_default_db: None, tmp_path: Path) -> None:
    facts = tmp_path / "facts.json"
    facts.write_text('{"rows": [], "transcripts": {}, "pane_argv": {}, "now": 0, "project_dir_names": []}')
    try:
        backfill.main(["--facts", str(facts)])
    except SystemExit as exc:
        assert "no database" not in str(exc)


def test_backfill_has_no_apply_flag() -> None:
    """u024-10: the docstring and the flag agree; the script never writes."""
    with pytest.raises(SystemExit):
        backfill.build_parser().parse_args(["--apply"])
    assert "--apply" not in (backfill.__doc__ or "").split("Usage::")[0].replace("There is no ``--apply``", "")


def test_importer_does_not_create_a_missing_database(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """u024-09: a typo'd --db is exit 2 and creates nothing."""
    missing = tmp_path / "typo.db"
    code = importer.main(["--db", str(missing), "--corpus", str(tmp_path)])
    assert code == 2
    assert not missing.exists()
    assert "COULD NOT READ" in capsys.readouterr().err


def test_importer_unreadable_schema_is_exit_2_not_a_traceback(tmp_path: Path) -> None:
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    assert importer.main(["--db", str(empty), "--corpus", str(tmp_path)]) == 2


def test_backfill_read_rows_does_not_create_a_missing_database(tmp_path: Path) -> None:
    missing = tmp_path / "typo.db"
    with pytest.raises(sqlite3.Error):
        backfill.read_rows(str(missing))
    assert not missing.exists()
    assert backfill.main(["--db", str(missing), "--projects-dir", str(tmp_path)]) == 2


def _classify_db(tmp_path: Path) -> Path:
    db = tmp_path / "carnivore.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, origin TEXT, kind TEXT)")
    return db


def test_classify_apply_refuses_without_a_backup(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """u024-11: --apply needs --require-backup."""
    db = _classify_db(tmp_path)
    assert classify.main(["--db", str(db), "--corpus", str(tmp_path), "--apply"]) == 2
    assert "--require-backup" in capsys.readouterr().err


def test_classify_apply_refuses_an_empty_backup(tmp_path: Path) -> None:
    db = _classify_db(tmp_path)
    empty = tmp_path / "bk.db"
    empty.write_bytes(b"")
    assert classify.main(["--db", str(db), "--corpus", str(tmp_path), "--apply", "--require-backup", str(empty)]) == 2


def test_classify_apply_with_a_backup_proceeds_and_a_locked_db_is_exit_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _classify_db(tmp_path)
    backup = tmp_path / "bk.db"
    backup.write_bytes(b"x")

    def _locked(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(classify, "apply_kinds", _locked)
    assert classify.main(["--db", str(db), "--corpus", str(tmp_path), "--apply", "--require-backup", str(backup)]) == 2


def test_classify_apply_waits_longer_than_the_default_busy_timeout() -> None:
    assert classify.APPLY_BUSY_TIMEOUT_S > 5


def test_backup_refusal_messages() -> None:
    assert legacy.backup_refusal(None)
    assert legacy.backup_refusal("/no/such/backup")
    assert legacy.backup_refusal(sys.executable) is None
