
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.core_owned_files.registry import CORE_OWNED, is_core_owned
from src.cplugs.host import purge_guard


def _task_manager(tmp_path: Path) -> Path:
    folder = tmp_path / "cplugs" / "huddle"
    (folder / "files" / "7").mkdir(parents=True)
    for name in ("huddle.db", "huddle.db-wal", "huddle.db.pre-cards-20261007T231623Z", "huddle.db.imported-20261020T000000Z", "IMPORTED.json"):
        (folder / name).write_bytes(b"core")
    (folder / "files" / "7" / "shot.png").write_bytes(b"png")
    (folder / "notes.txt").write_bytes(b"n")
    return folder


def test_registry_names_the_shared_store_and_nothing_else_of_the_plugin() -> None:
    assert is_core_owned("huddle", "huddle.db") and is_core_owned("huddle", "huddle.db-shm")
    assert is_core_owned("huddle", "huddle.db.bak-pre-rung12-20261004-194457")
    assert not is_core_owned("huddle", "files/7/huddle.db") and not is_core_owned("huddle", "notes.txt")
    assert not is_core_owned("reviewboard", "huddle.db") and "huddle" in CORE_OWNED


def test_purge_deletes_the_plugin_files_and_keeps_every_core_file(tmp_path: Path) -> None:
    folder = _task_manager(tmp_path)
    carried = purge_guard.purge(folder, "huddle", tmp_path / "cplugs")
    assert {p.name for p in carried.kept} == {"huddle.db", "huddle.db-wal", "huddle.db.pre-cards-20261007T231623Z",
                                              "huddle.db.imported-20261020T000000Z", "IMPORTED.json"}
    assert sorted(p.name for p in folder.iterdir()) == sorted(p.name for p in carried.kept)
    assert all(p.read_bytes() == b"core" for p in carried.kept)


def test_purge_of_a_plugin_with_nothing_core_owned_removes_the_folder(tmp_path: Path) -> None:
    folder = tmp_path / "cplugs" / "flow"
    (folder / "a").mkdir(parents=True)
    (folder / "a" / "x").write_bytes(b"1")
    purge_guard.purge(folder, "flow", tmp_path / "cplugs")
    assert not folder.exists()


def test_purge_refuses_a_folder_that_is_not_a_plugin_folder(tmp_path: Path) -> None:
    folder = _task_manager(tmp_path)
    for bad in (tmp_path, tmp_path / "cplugs", folder / "files"):
        with pytest.raises(purge_guard.PurgeRefused):
            purge_guard.purge(bad, "huddle", tmp_path / "cplugs")
    assert (folder / "huddle.db").exists() and (folder / "notes.txt").exists()


def test_plan_prices_without_touching_anything(tmp_path: Path) -> None:
    folder = _task_manager(tmp_path)
    carried = purge_guard.plan(folder, "huddle")
    assert len(carried.kept) == 5 and {p.name for p in carried.delete} == {"shot.png", "notes.txt"}
    assert purge_guard.plan(tmp_path / "nope", "huddle") == purge_guard.PurgePlan()
    assert (folder / "notes.txt").exists()
