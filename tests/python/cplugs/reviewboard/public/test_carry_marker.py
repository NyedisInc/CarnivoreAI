
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

import pytest

from src.cplugs.reviewboard.public import carry, links
from src.cplugs.sdk import CplugStorage, StorageSpec
from tests.python.cplugs.reviewboard.public.carry_fixtures import counts, make_old_folder, sha

SPEC = StorageSpec(db="links.db", migrations=links.MIGRATIONS, private=True)


@pytest.fixture
def folders(tmp_path: Path) -> Dict[str, Path]:
    return {"old": make_old_folder(tmp_path / "cplugs" / "publicboard"), "new": tmp_path / "cplugs" / "reviewboard"}


def backups(new: Path) -> list:
    return sorted(new.glob("carry-backup-*")) if new.is_dir() else []


def test_a_refused_carry_then_a_mint_never_skips_the_carry(folders: Dict[str, Path]) -> None:
    (folders["old"] / "responses.db").write_bytes(b"busy or damaged" * 50)
    assert carry.carry(folders["old"], folders["new"]).outcome == "refused"
    folders["new"].mkdir(parents=True, exist_ok=True)
    links.mint(CplugStorage(folders["new"], SPEC), "20261013-bar", "r1", "1d", "follow", "x" * 64)
    (folders["old"] / "responses.db").unlink()
    old_links = sha(folders["old"] / "links.db")
    again = carry.carry(folders["old"], folders["new"])
    assert again.outcome != "already_carried", "a links.db made by a mint is not the done marker"
    assert (again.outcome, again.reason) == ("refused", "target_exists")
    assert sha(folders["old"] / "links.db") == old_links and not (folders["new"] / carry.RECORD_FILE).exists()


def test_the_record_file_is_the_marker_and_is_written_last(folders: Dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    order = []
    real = os.replace
    monkeypatch.setattr(carry.os, "replace", lambda src, dst: (order.append(Path(dst).name), real(src, dst))[1])
    assert carry.carry(folders["old"], folders["new"]).outcome == "moved"
    assert order == ["responses.db", "links.db"]
    assert (folders["new"] / carry.RECORD_FILE).is_file()
    assert carry.carry(folders["old"], folders["new"]).outcome == "already_carried"


def test_a_failed_second_rename_publishes_no_links_db_and_no_record(folders: Dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    real, seen = os.replace, []

    def second_fails(src, dst):
        seen.append(Path(dst).name)
        if len(seen) == 2:
            raise OSError("simulated crash")
        return real(src, dst)

    monkeypatch.setattr(carry.os, "replace", second_fails)
    report = carry.carry(folders["old"], folders["new"])
    assert (report.outcome, report.reason) == ("refused", "carry_failed")
    assert not (folders["new"] / "links.db").exists() and not (folders["new"] / carry.RECORD_FILE).exists()


def test_a_crash_between_the_renames_is_resumed_from_the_backup(folders: Dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    real = os.replace
    monkeypatch.setattr(carry.os, "replace", lambda src, dst: (_ for _ in ()).throw(OSError("crash")) if str(dst).endswith("links.db") else real(src, dst))
    assert carry.carry(folders["old"], folders["new"]).reason == "carry_failed"
    assert (folders["new"] / "responses.db").exists() and backups(folders["new"])
    monkeypatch.setattr(carry.os, "replace", real)
    again = carry.carry(folders["old"], folders["new"])
    assert again.outcome == "moved", f"the retry the docstring promises ({again.reason})"
    assert counts(folders["new"]) == counts(folders["old"]) and (folders["new"] / carry.RECORD_FILE).is_file()
    assert backups(folders["new"]) == []


def test_a_finished_carry_deletes_its_backup_and_leaves_the_old_folder(folders: Dict[str, Path]) -> None:
    shas = {name: sha(folders["old"] / name) for name in ("links.db", "responses.db")}
    report = carry.carry(folders["old"], folders["new"])
    assert report.outcome == "moved" and backups(folders["new"]) == []
    assert sorted(p.name for p in folders["new"].iterdir()) == [carry.RECORD_FILE, "links.db", "responses.db"]
    assert {name: sha(folders["old"] / name) for name in shas} == shas


def test_a_stranger_in_the_target_is_not_resumed_from_an_unrelated_backup(folders: Dict[str, Path]) -> None:
    folders["new"].mkdir(parents=True)
    (folders["new"] / "responses.db").write_bytes(b"someone else's file")
    report = carry.carry(folders["old"], folders["new"])
    assert (report.outcome, report.reason) == ("refused", "target_exists")
