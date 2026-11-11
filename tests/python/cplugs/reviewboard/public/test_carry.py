
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest
from structlog.testing import capture_logs

from src.cplugs.reviewboard.public import carry
from tests.python.cplugs.reviewboard.public.carry_fixtures import counts, make_old_folder, sha


@pytest.fixture
def folders(tmp_path: Path) -> Dict[str, Path]:
    return {"old": make_old_folder(tmp_path / "cplugs" / "publicboard"), "new": tmp_path / "cplugs" / "reviewboard"}


def events(logs: List[Dict[str, Any]], name: str) -> List[Dict[str, Any]]:
    return [entry for entry in logs if entry["event"] == name]


def test_a_real_shaped_pair_moves_with_every_count_equal_and_is_logged(folders: Dict[str, Path]) -> None:
    before = counts(folders["old"])
    assert before["links.db:user_version"] == 3 and before["responses.db:user_version"] == 2 and before["links.db:links"] == 3
    with capture_logs() as logs:
        report = carry.carry(folders["old"], folders["new"])
    assert report.outcome == "moved" and report.moved is True
    assert counts(folders["new"]) == before
    assert report.counts["links.db:links"] == 3 and report.counts["responses.db:visitors"] == 2
    assert report.backup is not None and report.backup.parent == folders["new"] and not report.backup.exists()
    done = events(logs, "reviewboard_public_carried")
    assert len(done) == 1 and done[0]["log_level"] == "info"
    assert done[0]["counts"] == report.counts and done[0]["backup_removed"] == str(report.backup)


def test_the_old_folder_is_left_exactly_as_it_was(folders: Dict[str, Path]) -> None:
    shas = {name: sha(folders["old"] / name) for name in ("links.db", "responses.db")}
    carry.carry(folders["old"], folders["new"])
    assert {name: sha(folders["old"] / name) for name in ("links.db", "responses.db")} == shas
    assert sorted(p.name for p in folders["old"].iterdir()) == ["links.db", "responses.db"]


def test_a_second_run_moves_nothing_and_never_overwrites(folders: Dict[str, Path]) -> None:
    carry.carry(folders["old"], folders["new"])
    kept = {name: sha(folders["new"] / name) for name in ("links.db", "responses.db")}
    with capture_logs() as logs:
        again = carry.carry(folders["old"], folders["new"])
    assert again.outcome == "already_carried" and again.moved is False
    assert {name: sha(folders["new"] / name) for name in kept} == kept
    assert not events(logs, "reviewboard_public_carried")


def test_no_old_folder_is_nothing_to_carry_and_creates_nothing(tmp_path: Path) -> None:
    report = carry.carry(tmp_path / "cplugs" / "publicboard", tmp_path / "cplugs" / "reviewboard")
    assert report.outcome == "nothing_to_carry" and report.moved is False
    assert not (tmp_path / "cplugs" / "reviewboard").exists()


def test_links_without_a_responses_db_still_carry(folders: Dict[str, Path]) -> None:
    (folders["old"] / "responses.db").unlink()
    report = carry.carry(folders["old"], folders["new"])
    assert report.moved is True and (folders["new"] / "links.db").is_file() and not (folders["new"] / "responses.db").exists()


def refused(folders: Dict[str, Path], reason: str) -> None:
    with capture_logs() as logs:
        report = carry.carry(folders["old"], folders["new"])
    assert report.outcome == "refused" and report.moved is False and report.reason == reason
    warned = events(logs, "reviewboard_public_carry_refused")
    assert len(warned) == 1 and warned[0]["log_level"] == "warning" and warned[0]["reason"] == reason
    assert not (folders["new"] / "links.db").exists()
    assert not [p for p in folders["new"].glob("*.carry*")] if folders["new"].exists() else True


def test_a_newer_ladder_than_this_build_knows_is_refused(folders: Dict[str, Path]) -> None:
    import sqlite3
    with sqlite3.connect(folders["old"] / "links.db") as conn:
        conn.execute("PRAGMA user_version = 9")
    refused(folders, "unknown_schema_version")


def test_an_unreadable_database_is_refused(folders: Dict[str, Path]) -> None:
    (folders["old"] / "links.db").write_bytes(b"this is not a database" * 50)
    refused(folders, "unreadable_source")


def test_a_target_that_is_already_there_is_never_overwritten(folders: Dict[str, Path]) -> None:
    folders["new"].mkdir(parents=True)
    (folders["new"] / "responses.db").write_bytes(b"someone else's file")
    refused(folders, "target_exists")
    assert (folders["new"] / "responses.db").read_bytes() == b"someone else's file"


def test_a_copy_that_does_not_verify_is_refused_and_unpublished(folders: Dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    real = carry.count_rows
    monkeypatch.setattr(carry, "count_rows", lambda path, tables: {**real(path, tables), "links": -1} if path.name.endswith(".carry") else real(path, tables))
    refused(folders, "verification_failed")
