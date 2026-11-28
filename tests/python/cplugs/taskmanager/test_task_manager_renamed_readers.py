
from __future__ import annotations

import inspect
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest
import structlog

from src.core.core_owned_files.registry import CORE_OWNED
from src.core.inventory import file_claims
from src.core.work import file_refs, folders, storage as work_storage
from src.plugins.host import purge_guard
from src.plugins.taskmanager import file_removal, inbox_files
from src.plugins.taskmanager.store import TaskManagerStore
from src.plugins.sdk.context import CplugContext
from src.plugins.sdk.renamed_files import merged_item_files
from tests.python.cplugs.taskmanager.test_task_manager_renamed_files import (DATA, FILE_ID, NAME, move, new_files, new_storage,  # noqa: F401
                                                                         old_dir, temp_state)

LIST = "12"


def world(state: Path) -> SimpleNamespace:
    storage = new_storage(state)
    store = TaskManagerStore(storage, notify=lambda key: None)
    item = store.add(LIST, "has a file", actor="joe")["id"]
    rel = f"files/{item}/{NAME}"
    (old_dir(state) / "files" / str(item)).mkdir(exist_ok=True)
    (old_dir(state) / rel).write_bytes(DATA)
    parts = json.dumps({"files": [{"id": FILE_ID, "name": "a.png", "mime": "image/png", "size": len(DATA), "path": rel}]})
    store.post(item, "see", actor="joe", parts=parts)
    ctx = CplugContext("taskmanager", storage=storage, settings={}, notify=lambda name, key: None, log=structlog.get_logger(),
                       grants=frozenset(), capabilities={})
    return SimpleNamespace(storage=storage, store=store, item=item, rel=rel, ctx=ctx)


def copies(state: Path, item: int) -> List[Path]:
    return [p for p in (new_files(state) / str(item) / NAME, old_dir(state) / "files" / str(item) / NAME) if p.exists()]


def test_a_delete_after_the_move_takes_the_old_copy_too(temp_state: Path) -> None:
    w = world(temp_state)
    move(temp_state)
    assert len(copies(temp_state, w.item)) == 2
    assert file_removal.remove(w.ctx, w.item, FILE_ID)["bytes"] == "deleted"
    assert copies(temp_state, w.item) == []


def test_a_delete_before_the_marker_never_comes_back(temp_state: Path) -> None:
    w = world(temp_state)
    (new_files(temp_state) / str(w.item)).mkdir(parents=True)
    (new_files(temp_state) / w.rel.split("/", 1)[1]).write_bytes(DATA)
    assert file_removal.remove(w.ctx, w.item, FILE_ID)["bytes"] == "deleted"
    assert copies(temp_state, w.item) == []
    move(temp_state)
    assert copies(temp_state, w.item) == []


def test_a_file_only_in_the_old_folder_can_be_deleted(temp_state: Path) -> None:
    w = world(temp_state)
    move(temp_state, free=1024)
    assert file_removal.remove(w.ctx, w.item, FILE_ID)["bytes"] == "deleted"
    assert copies(temp_state, w.item) == []


def test_deleting_a_task_removes_its_old_folder_too(temp_state: Path) -> None:
    w = world(temp_state)
    move(temp_state)
    w.store.delete(w.item, actor="joe")
    assert not (new_files(temp_state) / str(w.item)).exists() and not (old_dir(temp_state) / "files" / str(w.item)).exists()


def test_the_merged_view_is_per_file(temp_state: Path) -> None:
    move(temp_state)
    later = old_dir(temp_state) / "files" / "7" / "cd34ab12-b.txt"
    later.write_bytes(b"b")
    fresh = new_files(temp_state) / "7" / "ef56ab78-c.txt"
    fresh.write_bytes(b"c")
    roots = folders.files_roots(temp_state)
    assert sorted(merged_item_files(*roots, "7")) == sorted([new_files(temp_state) / "7" / NAME, fresh, later])
    (new_files(temp_state) / "7" / NAME).unlink()
    assert sorted(merged_item_files(*roots, "7")) == sorted([fresh, later])


def claims(state: Path, monkeypatch: pytest.MonkeyPatch, items: List[int]) -> List[str]:
    monkeypatch.setattr(file_claims, "claimed_item_ids", lambda conn, scope: items)
    monkeypatch.setattr(file_claims, "_ids_where", lambda *a, **k: [])
    blockers: List[str] = []
    arts = file_claims._task_and_desk(SimpleNamespace(state_dir=state), None, None, blockers)  # type: ignore[arg-type]
    assert blockers == []
    return sorted(a.what for a in arts if a.store == file_claims.STORE_TASK_FILES)


def test_the_inventory_carries_both_folders_files_of_one_item(temp_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    move(temp_state, free=1024)
    fresh = new_files(temp_state) / "7" / "ef56ab78-c.txt"
    fresh.parent.mkdir(parents=True)
    fresh.write_bytes(b"c")
    assert claims(temp_state, monkeypatch, [7]) == sorted([str(fresh.parent), str(old_dir(temp_state) / "files" / "7")])


def test_the_inventory_never_carries_a_deleted_file(temp_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    move(temp_state)
    (new_files(temp_state) / "7" / NAME).unlink()
    (new_files(temp_state) / "7").rmdir()
    assert claims(temp_state, monkeypatch, [7]) == []


def test_inbox_files_are_read_from_both_folders_and_swept_in_both(temp_state: Path) -> None:
    w = world(temp_state)
    entry = old_dir(temp_state) / inbox_files.DIR_NAME / "entry-12"
    entry.mkdir(parents=True)
    (entry / "ef56ab78-shot.png").write_bytes(b"shot")
    assert [f["name"] for f in inbox_files.listing(w.storage, 12)] == ["shot.png"]
    staged = old_dir(temp_state) / inbox_files.DIR_NAME / inbox_files.staged_dir(w.storage, LIST).relative_to(
        w.storage.path / inbox_files.DIR_NAME)
    staged.mkdir(parents=True)
    (staged / "0a1b2c3d-paste.txt").write_bytes(b"p")
    assert [p.name for p in inbox_files.resolve_staged(w.storage, LIST, ["0a1b2c3d"])] == ["0a1b2c3d-paste.txt"]
    assert inbox_files.attach_to_item(w.store, 12, w.item) == 1
    old = time.time() - inbox_files.STAGED_TTL_S - 10
    os.utime(staged / "0a1b2c3d-paste.txt", (old, old))
    os.utime(entry, (old, old))
    assert inbox_files.sweep(w.storage, keep=set()) == 2
    assert not entry.exists() and not (staged / "0a1b2c3d-paste.txt").exists()


def test_the_crate_import_writes_into_the_current_folder(temp_state: Path) -> None:
    assert file_refs.FILES_DIR == tuple(folders.files_rel(folders.CURRENT_ID).split("/"))
    assert '"huddle"' not in inspect.getsource(file_refs)


def test_the_id_slice_s4_flips_cannot_drop_the_core_owned_key(temp_state: Path) -> None:
    assert (folders.OLD_ID, folders.NEW_ID) == ("huddle", "taskmanager")
    assert work_storage.FOLDER_NAME == folders.CURRENT_ID
    assert set(folders.IDS_NEWEST_FIRST) == {folders.OLD_ID, folders.NEW_ID} == set(CORE_OWNED)
    assert "CURRENT_ID" not in inspect.getsource(folders).split("IDS_NEWEST_FIRST", 1)[1].split("\n", 1)[0]
    for plugin_id in (folders.OLD_ID, folders.NEW_ID):
        folder = temp_state / "cplugs" / plugin_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "huddle.db").write_bytes(b"db")
        assert folder / "huddle.db" in purge_guard.plan(folder, plugin_id).kept
