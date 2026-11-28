
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from src.core.work import storage as work_storage
from src.plugins.taskmanager import file_removal, files as item_files
from src.plugins.taskmanager.rules import TaskManagerFileShared
from src.plugins.taskmanager.cli import move_files_to_root as cli
from tests.python.cplugs.taskmanager.test_task_manager_renamed_files import DATA, FILE_ID, NAME, move, new_files, old_dir, temp_state  # noqa: F401
from tests.python.cplugs.taskmanager.test_task_manager_renamed_readers import world
from tests.python.cplugs.taskmanager.test_task_manager_renamed_r2 import stale_events


def entry_for(rel: str) -> dict:
    return {"id": FILE_ID, "name": "a.png", "mime": "image/png", "size": len(DATA), "path": rel}


def test_the_agent_read_path_finds_a_file_only_the_old_folder_holds(temp_state: Path) -> None:
    w = world(temp_state)
    move(temp_state)
    later = old_dir(temp_state) / "files" / str(w.item) / "cd34ab12-b.txt"
    later.write_bytes(b"b")
    [out] = item_files.for_agent(w.storage, [{**entry_for(f"files/{w.item}/cd34ab12-b.txt"), "name": "b.txt", "size": 1}])
    assert Path(out["path"]) == later.resolve() and Path(out["path"]).is_file()


def test_the_agent_read_path_is_unchanged_for_a_file_in_the_new_folder(temp_state: Path) -> None:
    w = world(temp_state)
    move(temp_state)
    [out] = item_files.for_agent(w.storage, [entry_for(w.rel)])
    assert Path(out["path"]) == (new_files(temp_state) / str(w.item) / NAME).resolve()


def test_another_items_relative_path_to_an_old_only_file_counts_as_sharing_the_bytes(temp_state: Path) -> None:
    w = world(temp_state)
    move(temp_state)
    other = w.store.add("12", "second", actor="joe")["id"]
    rel = f"files/{w.item}/cd34ab12-b.txt"
    only_old = old_dir(temp_state) / rel
    only_old.write_bytes(b"b")
    parts = json.dumps({"files": [{**entry_for(rel), "id": "cd34ab12", "name": "b.txt", "size": 1}]})
    w.store.post(w.item, "a", actor="joe", parts=parts)
    w.store.post(other, "b", actor="joe", parts=parts)
    with pytest.raises(TaskManagerFileShared):
        file_removal.remove(w.ctx, w.item, "cd34ab12")
    assert only_old.read_bytes() == b"b"


def test_apply_takes_the_old_copy_before_moving_a_file(temp_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(work_storage, "FOLDER_NAME", "taskmanager")
    w = world(temp_state)
    move(temp_state)
    root = temp_state / "tm"
    root.mkdir()
    (root / ".boards-root").write_text("")
    old_file = old_dir(temp_state) / w.rel
    assert old_file.exists()
    code = cli.main(["--work-db", str(w.storage.db_path), "--root", str(root), "--apply"], io.StringIO())
    assert code == 0
    assert not old_file.exists()
    assert stale_events(temp_state) == []
    assert not (new_files(temp_state) / str(w.item) / NAME).exists()
