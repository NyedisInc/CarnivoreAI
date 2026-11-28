
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import List

import pytest
from structlog.testing import capture_logs

from src.core.work import file_refs, folders, storage as work_storage
from src.core.work.storage import WorkStorage
from src.plugins.taskmanager import files as item_files, inbox_files, moves
from src.plugins.taskmanager.store import TaskManagerStore
from src.plugins.sdk import renamed_files as sdk_renamed
from tests.python.cplugs.taskmanager.test_task_manager_renamed_files import (DATA, FILE_ID, NAME, move, new_files, new_storage,  # noqa: F401
                                                                         old_dir, temp_state)
from tests.python.cplugs.taskmanager.test_task_manager_renamed_readers import claims, world

LIST = "12"


def stale_events(state: Path) -> List[dict]:
    with capture_logs() as logs:
        move(state)
    return [e for e in logs if e["event"] == "cplug_renamed_files_marker_stale"]




def test_a_reply_that_moves_a_pre_move_file_into_the_task_folder_takes_the_old_copy(temp_state: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    storage = new_storage(temp_state)
    store = TaskManagerStore(storage, notify=lambda key: None)
    item = store.add(LIST, "unposted upload", actor="joe")["id"]
    old_file = old_dir(temp_state) / "files" / str(item) / NAME
    old_file.parent.mkdir(parents=True, exist_ok=True)
    old_file.write_bytes(DATA)
    move(temp_state)
    pastes = tmp_path_factory.mktemp("pastes")
    [entry] = item_files.attach(storage, item, [FILE_ID], pastes)
    assert entry["path"] == str(pastes / NAME) and (pastes / NAME).read_bytes() == DATA
    assert not old_file.exists()
    assert stale_events(temp_state) == []
    assert not (new_files(temp_state) / str(item) / NAME).exists()


def test_a_task_delete_removes_the_old_folder_first_and_keeps_the_new_one_when_that_fails(temp_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(temp_state)
    move(temp_state)
    real = moves.remove_folder
    calls: List[Path] = []

    def fail_old(folder: Path) -> bool:
        calls.append(folder)
        return False if old_dir(temp_state) in folder.parents else real(folder)

    monkeypatch.setattr(moves, "remove_folder", fail_old)
    w.store.delete(w.item, actor="joe")
    assert calls == [old_dir(temp_state) / "files" / str(w.item)]
    assert (new_files(temp_state) / str(w.item) / NAME).is_file()
    assert stale_events(temp_state) == []


def test_a_task_delete_removes_both_folders_old_first(temp_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(temp_state)
    move(temp_state)
    real, calls = moves.remove_folder, []
    monkeypatch.setattr(moves, "remove_folder", lambda folder: calls.append(folder) or real(folder))
    w.store.delete(w.item, actor="joe")
    assert calls == [old_dir(temp_state) / "files" / str(w.item), new_files(temp_state) / str(w.item)]
    assert not (new_files(temp_state) / str(w.item)).exists() and not (old_dir(temp_state) / "files" / str(w.item)).exists()


def test_the_orphan_sweep_takes_the_twin_first_and_keeps_the_new_file_when_it_cannot(temp_state: Path) -> None:
    move(temp_state)
    storage = new_storage(temp_state)
    old_item = old_dir(temp_state) / "files" / "7"
    old_item.chmod(0o500)
    try:
        with capture_logs() as logs:
            removed = item_files.sweep_orphans(storage, now=time.time() + 10 * item_files.ORPHAN_AGE_S)
    finally:
        old_item.chmod(0o700)
    assert removed == 0
    assert (new_files(temp_state) / "7" / NAME).is_file() and (old_item / NAME).is_file()
    assert any(e["event"] == "task_manager_orphan_twin_left" for e in logs)
    assert stale_events(temp_state) == []


def test_the_orphan_sweep_takes_both_copies(temp_state: Path) -> None:
    move(temp_state)
    assert item_files.sweep_orphans(new_storage(temp_state), now=time.time() + 10 * item_files.ORPHAN_AGE_S) == 1
    assert not (new_files(temp_state) / "7" / NAME).exists() and not (old_dir(temp_state) / "files" / "7" / NAME).exists()




def test_with_no_rename_an_item_folder_with_a_dot_file_is_claimed_whole(temp_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (old_dir(temp_state) / "files" / "7" / ".DS_Store").write_bytes(b"ds")
    assert claims(temp_state, monkeypatch, [7]) == [str(old_dir(temp_state) / "files" / "7")]


def test_with_no_rename_the_inbox_listing_follows_a_symlink_as_master_did(temp_state: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    storage = WorkStorage(old_dir(temp_state), temp_state)
    real = tmp_path_factory.mktemp("elsewhere")
    (real / "ef56ab78-shot.png").write_bytes(b"shot")
    base = old_dir(temp_state) / inbox_files.DIR_NAME
    base.mkdir(parents=True)
    (base / "entry-12").symlink_to(real, target_is_directory=True)
    assert [f["name"] for f in inbox_files.listing(storage, 12)] == ["shot.png"]




def test_an_old_folder_only_file_is_recorded_relative(temp_state: Path) -> None:
    move(temp_state)
    later = old_dir(temp_state) / "files" / "7" / "cd34ab12-b.txt"
    later.write_bytes(b"b")
    storage = new_storage(temp_state)
    [entry] = item_files.attach(storage, 7, ["cd34ab12"])
    assert entry["path"] == "files/7/cd34ab12-b.txt"
    assert item_files.stored_file(storage, entry["path"]) == later


def test_the_conflict_line_says_the_new_file_wins(temp_state: Path) -> None:
    (new_files(temp_state) / "7").mkdir(parents=True)
    (new_files(temp_state) / "7" / NAME).write_bytes(b"different")
    with capture_logs() as logs:
        move(temp_state)
    [line] = [e for e in logs if e["event"] == "cplug_renamed_files_conflict"]
    assert "new folder's file wins" in line["reason"] and "served behind" not in line["reason"]


def test_the_servable_rule_lives_in_the_sdk(temp_state: Path) -> None:
    move(temp_state)
    old_files, new = old_dir(temp_state) / "files", new_files(temp_state)
    later = old_files / "7" / "cd34ab12-b.txt"
    later.write_bytes(b"b")
    assert sdk_renamed.servable(new, old_files, later)
    assert not sdk_renamed.servable(new, old_files, old_files / "7" / NAME)
    (new / "7" / NAME).unlink()
    assert not sdk_renamed.servable(new, old_files, old_files / "7" / NAME)
    assert sdk_renamed.servable(new, old_files, new / "7" / "x")
    assert sdk_renamed.servable(new, None, later)


def test_storage_for_binds_the_old_folder_once_the_id_moved(temp_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert work_storage.storage_for(temp_state).previous_path == old_dir(temp_state)
    monkeypatch.setattr(work_storage, "FOLDER_NAME", folders.OLD_ID)
    assert work_storage.storage_for(temp_state).previous_path is None
    monkeypatch.setattr(work_storage, "FOLDER_NAME", folders.NEW_ID)
    storage = work_storage.storage_for(temp_state)
    assert storage.path == temp_state / "cplugs" / "taskmanager" and storage.previous_path == old_dir(temp_state)


def test_the_file_home_copies_from_the_old_folder_when_the_new_one_lacks_the_bytes(temp_state: Path) -> None:
    home = file_refs.FileHome(temp_state, local_files=new_files(temp_state), previous_local_files=old_dir(temp_state) / "files",
                              keep_unresolved=True)
    parts = json.dumps({"files": [{"id": FILE_ID, "name": "a.png", "mime": "image/png", "size": len(DATA), "path": f"files/7/{NAME}"}]})
    out, _text = home.rewrite_message(parts, "", 7, 9)
    assert json.loads(out)["files"][0]["path"] == f"files/9/{NAME}" and home.unresolved == []
    assert (home.files_root / "9" / NAME).read_bytes() == DATA


def test_a_file_removal_whose_old_copy_cannot_move_keeps_the_new_copy(temp_state: Path) -> None:
    from src.plugins.taskmanager import file_removal
    from src.plugins.taskmanager.rules import TaskManagerBytesNotRemoved

    w = world(temp_state)
    move(temp_state)
    old_item = old_dir(temp_state) / "files" / str(w.item)
    old_item.chmod(0o500)
    try:
        with pytest.raises(TaskManagerBytesNotRemoved):
            file_removal.remove(w.ctx, w.item, FILE_ID)
    finally:
        old_item.chmod(0o700)
    assert (new_files(temp_state) / str(w.item) / NAME).is_file() and (old_item / NAME).is_file()
    assert stale_events(temp_state) == []
    assert file_removal.remove(w.ctx, w.item, FILE_ID)["bytes"] == "deleted"
    assert not (new_files(temp_state) / str(w.item) / NAME).exists() and not (old_item / NAME).exists()
