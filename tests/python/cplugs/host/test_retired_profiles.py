
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from src.core.plugin_health import sizes
from src.plugins.host import registry_store, retired_profiles
from src.plugins.runtime import sandbox

MOVED_UUID = "a" * 32
UNMOVED_UUID = "b" * 32
GONE_UUID = "c" * 32
TODAY = date(2026, 11, 10)


@pytest.fixture()
def state(tmp_path: Path) -> Path:
    root = tmp_path / "state"
    old = retired_profiles.old_profiles_dir(root)
    old.mkdir(parents=True)
    (root / "plugin-data" / MOVED_UUID).mkdir(parents=True)
    (root / "cplugs" / UNMOVED_UUID).mkdir(parents=True)
    for key in (MOVED_UUID, UNMOVED_UUID, GONE_UUID, "huddle"):
        (old / f"{key}.sb").write_text(f"(version 1) ; {key}\n")
    return root


def test_dead_profiles_are_the_ones_no_plugin_reads(state: Path) -> None:
    names = {p.name for p in retired_profiles.dead_profiles(state)}
    assert names == {f"{MOVED_UUID}.sb", f"{GONE_UUID}.sb"}
    assert sandbox.profile_path_for(state / "cplugs" / UNMOVED_UUID) == retired_profiles.old_profiles_dir(state) / f"{UNMOVED_UUID}.sb"


def test_moved_into_the_newest_backup_with_its_mtime_kept(state: Path) -> None:
    older, newer = registry_store.backup_dir(state, 1), registry_store.backup_dir(state, 2)
    older.mkdir(parents=True)
    newer.mkdir()
    os.utime(older, ns=(1_000_000_000, 1_000_000_000))
    os.utime(newer, ns=(2_000_000_000, 2_000_000_000))
    moved = retired_profiles.retire_old_profiles(state, TODAY)
    target = newer / retired_profiles.RETIRED_DIR_NAME
    assert sorted(moved) == sorted([target / f"{MOVED_UUID}.sb", target / f"{GONE_UUID}.sb"])
    assert (target / f"{MOVED_UUID}.sb").read_text() == f"(version 1) ; {MOVED_UUID}\n"
    assert newer.stat().st_mtime_ns == 2_000_000_000
    assert registry_store.backups_newest_first(state)[0] == newer
    left = {p.name for p in retired_profiles.old_profiles_dir(state).iterdir()}
    assert left == {f"{UNMOVED_UUID}.sb", "huddle.sb"}


def test_without_a_backup_they_go_to_a_dated_folder_and_a_second_run_is_a_no_op(state: Path) -> None:
    moved = retired_profiles.retire_old_profiles(state, TODAY)
    target = state / "cplugs" / retired_profiles.RETIRED_DIR_NAME / TODAY.isoformat()
    assert {p.parent for p in moved} == {target} and len(moved) == 2
    assert retired_profiles.retire_old_profiles(state, TODAY) == []


def test_a_name_already_there_is_never_overwritten(state: Path) -> None:
    target = state / "cplugs" / retired_profiles.RETIRED_DIR_NAME / TODAY.isoformat()
    target.mkdir(parents=True)
    (target / f"{MOVED_UUID}.sb").write_text("earlier\n")
    retired_profiles.retire_old_profiles(state, TODAY)
    assert (target / f"{MOVED_UUID}.sb").read_text() == "earlier\n"
    assert (target / f"{MOVED_UUID}.sb.1").read_text() == f"(version 1) ; {MOVED_UUID}\n"


def test_a_failure_never_raises(state: Path) -> None:
    (state / "cplugs" / retired_profiles.RETIRED_DIR_NAME).write_text("in the way\n")
    assert retired_profiles.retire_old_profiles(state, TODAY) == []
    assert (retired_profiles.old_profiles_dir(state) / f"{MOVED_UUID}.sb").is_file()


def test_no_old_folder_is_nothing(tmp_path: Path) -> None:
    assert retired_profiles.retire_old_profiles(tmp_path / "fresh", TODAY) == []


def test_health_host_folders_match_the_runtime_names() -> None:
    assert sizes.HOST_FOLDERS == {sandbox.PROFILES_DIR_NAME, retired_profiles.RETIRED_DIR_NAME}
