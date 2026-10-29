
from __future__ import annotations

import os
import shutil
import sqlite3
import time
from pathlib import Path
from contextlib import closing
from typing import List, Optional, Set, Tuple

import pytest

from src.cplugs.huddle import files, store_identity, task_sweep
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.storage import WorkStorage
from src.cplugs.sdk import ports, task_folders

DAY = files.ORPHAN_AGE_S
OLD = 3 * DAY


class FakeRoot:

    def __init__(self, folder: Path):
        self.folder = folder

    def root(self) -> Path:
        return self.folder


@pytest.fixture
def storage(tmp_path: Path) -> WorkStorage:
    return WorkStorage(tmp_path / "state")


@pytest.fixture
def store(storage: WorkStorage) -> TaskManagerStore:
    return TaskManagerStore(storage, notify=lambda t: None)


@pytest.fixture
def root(tmp_path: Path):
    folder = tmp_path / "tm"
    folder.mkdir()
    ports.register(task_folders.ROOT_PORT, FakeRoot(folder))
    yield folder
    ports.unregister(task_folders.ROOT_PORT)


def own_id(storage: WorkStorage) -> str:
    with closing(storage.connect(True)) as conn, conn:
        return store_identity.ensure(conn)


def make_task(store: TaskManagerStore, root: Path, text: str = "task", store_id: Optional[str] = "ours") -> Tuple[int, Path]:
    item = store.add("all", text, actor="joe")
    ident = own_id(store._storage) if store_id == "ours" else store_id
    folder = task_folders.ensure_task(root, item["id"], "all", None, text, store_id=ident)
    for kind in (task_folders.PASTES, task_folders.ARTIFACTS):
        task_folders.kind_dir(folder, kind)
    return item["id"], folder


def stored(folder: Path, kind: str, name: str, age_s: float = OLD) -> Path:
    path = folder / kind / name
    path.write_bytes(b"bytes")
    path.chmod(0o600)
    stamp = time.time() - age_s
    os.utime(path, (stamp, stamp), follow_symlinks=False)
    return path


def name_it(store: TaskManagerStore, item_id: int, path: Path) -> None:
    entry = {"id": path.name[:8], "name": files.name_of(path.name), "mime": "text/plain", "size": 5, "path": str(path)}
    store.post(item_id, "here", actor="joe", parts=files.parts_of([entry]))


def test_an_unreferenced_old_file_in_pastes_and_artifacts_is_swept(store, storage, root):
    _, task = make_task(store, root)
    paste = stored(task, "pastes", "ab12cd34-shot.txt")
    page = stored(task, "artifacts", "ef56ab78-artifact.html")
    assert task_sweep.sweep_all(storage) == 2
    assert not paste.exists() and not page.exists()


def test_a_referenced_file_stays(store, storage, root):
    item, task = make_task(store, root)
    kept = stored(task, "pastes", "ab12cd34-kept.txt")
    name_it(store, item, kept)
    assert task_sweep.sweep_all(storage) == 0 and kept.exists()


def test_a_file_named_by_a_message_on_another_task_stays(store, storage, root):
    _, task = make_task(store, root, "one")
    other, _ = make_task(store, root, "two")
    shared = stored(task, "pastes", "ab12cd34-shared.txt")
    name_it(store, other, shared)
    assert task_sweep.sweep_all(storage) == 0 and shared.exists()


def test_a_fresh_file_stays(store, storage, root):
    _, task = make_task(store, root)
    fresh = stored(task, "pastes", "ab12cd34-fresh.txt", age_s=60)
    just_short = stored(task, "artifacts", "ef56ab78-artifact.html", age_s=DAY - 600)
    assert task_sweep.sweep_all(storage) == 0
    assert fresh.exists() and just_short.exists()


def test_the_files_of_a_done_or_hidden_task_stay_until_it_is_purged(store, storage, root):
    done, done_folder = make_task(store, root, "done")
    hidden, hidden_folder = make_task(store, root, "hidden")
    done_file = stored(done_folder, "pastes", "ab12cd34-done.txt")
    hidden_file = stored(hidden_folder, "artifacts", "ef56ab78-artifact.html")
    name_it(store, done, done_file)
    name_it(store, hidden, hidden_file)
    store.update(done, actor="joe", approve=True)
    store.update(hidden, actor="joe", approve=True)
    assert store.remove_completed("all", actor="joe")["removed"] == [done, hidden]
    assert task_sweep.sweep_all(storage) == 0
    assert done_file.exists() and hidden_file.exists()


def test_the_leftovers_of_a_purged_task_are_swept(store, storage, root):
    item, task = make_task(store, root)
    leftover = stored(task, "pastes", "ab12cd34-left.txt")
    name_it(store, item, leftover)
    store.delete(item, actor="joe")
    assert not leftover.exists()
    task_folders.kind_dir(task, "pastes")
    leftover = stored(task, "pastes", leftover.name)
    assert task_sweep.sweep_all(storage) == 1 and not leftover.exists()


def test_the_owners_own_files_and_the_boards_are_never_touched(store, storage, root):
    _, task = make_task(store, root)
    gitignore = task / "pastes" / ".gitignore"
    mine = stored(task, "pastes", "my-own-notes.txt")
    short_id = stored(task, "artifacts", "abc-not-eight.txt")
    upper = stored(task, "pastes", "AB12CD34-upper.txt")
    board = task / "boards" / "20261028-board"
    board.mkdir(parents=True)
    on_board = board / "ab12cd34-board.txt"
    on_board.write_bytes(b"x")
    os.utime(on_board, (time.time() - OLD,) * 2)
    marker = task / task_folders.TASK_MARKER
    os.utime(gitignore, (time.time() - OLD,) * 2)
    assert task_sweep.sweep_all(storage) == 0
    assert all(p.exists() for p in (gitignore, mine, short_id, upper, on_board, marker))


def test_a_symlink_is_neither_followed_nor_taken(store, storage, root, tmp_path):
    _, task = make_task(store, root)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"precious")
    os.utime(outside, (time.time() - OLD,) * 2)
    link = task / "pastes" / "ab12cd34-link.txt"
    link.symlink_to(outside)
    assert task_sweep.sweep_all(storage) == 0
    assert outside.read_bytes() == b"precious" and link.is_symlink()


def test_a_symlinked_pastes_folder_sends_the_sweep_nowhere(store, storage, root, tmp_path):
    _, task = make_task(store, root)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    victim = elsewhere / "ab12cd34-victim.txt"
    victim.write_bytes(b"precious")
    os.utime(victim, (time.time() - OLD,) * 2)
    shutil.rmtree(task / "pastes")
    os.symlink(elsewhere, task / "pastes")
    assert task_sweep.sweep_all(storage) == 0 and victim.exists()


def test_a_set_aside_copy_in_a_task_folder_goes_after_the_grace(store, storage, root):
    _, task = make_task(store, root)
    old = stored(task, "pastes", f"{files.ASIDE_PREFIX}ab12cd34-gone.txt", age_s=files.ASIDE_GRACE_S + 5)
    fresh = stored(task, "artifacts", f"{files.ASIDE_PREFIX}ef56ab78-artifact.html", age_s=files.ASIDE_GRACE_S - 60)
    assert task_sweep.sweep_all(storage) == 1
    assert not old.exists() and fresh.exists()


def test_a_reply_posted_after_the_sweep_listed_its_files_keeps_its_file(store, storage, root, monkeypatch):
    item, task = make_task(store, root)
    racing = stored(task, "pastes", "ab12cd34-racing.txt")
    listed = task_sweep._candidates
    replied = []

    def list_then_reply(folder: Path) -> List[Path]:
        found = listed(folder)
        if racing in found and not replied:
            name_it(store, item, racing)
            replied.append(True)
        return found

    monkeypatch.setattr(task_sweep, "_candidates", list_then_reply)
    assert task_sweep.sweep_all(storage) == 0 and racing.exists()


def test_the_sweep_holds_the_write_lock_while_it_decides(store, storage, root, monkeypatch):
    _, task = make_task(store, root)
    orphan = stored(task, "pastes", "ab12cd34-orphan.txt")
    seen = {}
    decide = task_sweep._sweepable

    def probe(path: Path, keep: Set[str], at: float, age_s: float) -> bool:
        with closing(storage.connect(True)) as other:
            other.execute("PRAGMA busy_timeout = 0")
            try:
                other.execute("BEGIN IMMEDIATE")
                seen["locked"] = False
                other.rollback()
            except sqlite3.OperationalError as exc:
                seen["locked"] = "locked" in str(exc)
        return decide(path, keep, at, age_s)

    monkeypatch.setattr(task_sweep, "_sweepable", probe)
    assert task_sweep.sweep_all(storage) == 1 and seen == {"locked": True} and not orphan.exists()


def test_a_store_that_was_never_written_judges_nothing(tmp_path, root):
    never = WorkStorage(tmp_path / "never")
    folder = task_folders.ensure_task(root, 9, "all", None, "ghost")
    task_folders.kind_dir(folder, "pastes")
    path = stored(folder, "pastes", "ab12cd34-x.txt")
    assert task_sweep.sweep_task_folders(never, root) == 0 and path.exists() and not never.db_path.exists()


def test_with_no_task_folder_set_only_the_plugin_folder_is_swept(store, storage):
    assert ports.get(task_folders.ROOT_PORT) is None
    assert task_sweep.sweep_all(storage) == 0


def test_a_moved_upload_counts_its_age_from_the_move(tmp_path):
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    upload = plugin / "ab12cd34-old.txt"
    upload.write_bytes(b"x")
    os.utime(upload, (time.time() - OLD,) * 2)
    pastes = tmp_path / "pastes"
    pastes.mkdir()
    moved = files.move_into(upload, pastes)
    assert time.time() - moved.stat().st_mtime < 60


def test_a_read_error_deletes_nothing(store, storage, root, monkeypatch):
    item, task = make_task(store, root)
    kept = stored(task, "pastes", "ab12cd34-kept.txt")
    name_it(store, item, kept)
    monkeypatch.setattr(files, "PARTS_SQL", "no_such_column = 1")
    with pytest.raises(sqlite3.OperationalError):
        task_sweep.sweep_task_folders(storage, root)
    assert kept.exists()


def test_a_read_error_deletes_nothing_in_the_plugin_folder_either(store, storage, monkeypatch):
    kept = files.save(storage, 7, "kept.txt", b"k")
    path = files.locate(storage, 7, kept["id"])
    os.utime(path, (time.time() - OLD,) * 2)
    monkeypatch.setattr(files, "PARTS_SQL", "no_such_column = 1")
    with pytest.raises(sqlite3.OperationalError):
        files.sweep_orphans(storage)
    assert path.exists()


def test_a_missing_messages_table_names_nothing():
    with closing(sqlite3.connect(":memory:")) as bare:
        bare.row_factory = sqlite3.Row
        assert task_sweep.referenced_names(bare) == set()


def test_a_folder_of_an_item_this_database_does_not_have_is_left(store, storage, root):
    store.add("all", "ours", actor="joe")
    strange = task_folders.ensure_task(root, 987654, "all", None, "elsewhere", store_id=own_id(storage))
    task_folders.kind_dir(strange, "pastes")
    theirs = stored(strange, "pastes", "ab12cd34-theirs.txt")
    assert task_sweep.sweep_all(storage) == 0 and theirs.exists()


def test_a_folder_whose_marker_names_another_list_is_left(store, storage, root):
    item = store.add("all", "moved", actor="joe")["id"]
    folder = task_folders.ensure_task(root, item, "12", "Carnivore", "moved", store_id=own_id(storage))
    task_folders.kind_dir(folder, "pastes")
    kept = stored(folder, "pastes", "ab12cd34-kept.txt")
    assert task_sweep.sweep_all(storage) == 0 and kept.exists()


@pytest.mark.parametrize("name", ["ab12cd34-shot 2.png", "ab12cd34-notes (conflict).txt", "ab12cd34--odd.txt"])
def test_a_name_the_store_could_not_have_made_is_left(store, storage, root, name):
    _, task = make_task(store, root)
    theirs = stored(task, "artifacts", name)
    assert task_sweep.sweep_all(storage) == 0 and theirs.exists()


def test_a_file_of_the_store_shape_but_not_its_mode_is_left(store, storage, root):
    _, task = make_task(store, root)
    theirs = stored(task, "artifacts", "20261027-design-notes.md")
    theirs.chmod(0o644)
    assert task_sweep.sweep_all(storage) == 0 and theirs.exists()


def test_a_set_aside_copy_a_thread_still_names_is_left(store, storage, root):
    item, task = make_task(store, root)
    live = stored(task, "pastes", "ab12cd34-shot.png")
    name_it(store, item, live)
    aside = live.with_name(f"{files.ASIDE_PREFIX}{live.name}")
    os.rename(live, aside)
    os.utime(aside, (time.time() - 2 * files.ASIDE_GRACE_S,) * 2)
    assert task_sweep.sweep_all(storage) == 0 and aside.exists()


def test_a_failed_stamp_never_undoes_a_completed_move(tmp_path, monkeypatch):
    plugin, pastes = tmp_path / "plugin", tmp_path / "pastes"
    plugin.mkdir()
    pastes.mkdir()
    upload = plugin / "ab12cd34-a.txt"
    upload.write_bytes(b"x")

    def refuse(path, *args, **kwargs):
        raise PermissionError("not ours to stamp")

    monkeypatch.setattr(files.os, "utime", refuse)
    moved = files.move_into(upload, pastes)
    assert moved.exists() and not upload.exists()


def test_a_reply_that_reattaches_a_leftover_stamps_it(store, storage, root):
    item, task = make_task(store, root)
    pastes = task / "pastes"
    leftover = stored(task, "pastes", "ab12cd34-left.txt")
    files.attach(storage, item, ["ab12cd34"], pastes, [pastes])
    assert time.time() - leftover.stat().st_mtime < 60


def test_a_folder_of_another_store_with_the_same_item_and_list_is_left(store, storage, root):
    _, theirs_folder = make_task(store, root, "theirs", store_id="0f0f0f0f0f0f0f0f")
    theirs = stored(theirs_folder, "pastes", "ab12cd34-theirs.txt")
    own_id(storage)
    assert task_sweep.sweep_all(storage) == 0 and theirs.exists()


def test_a_folder_with_no_store_id_is_left(store, storage, root):
    _, old_folder = make_task(store, root, "legacy", store_id=None)
    assert task_folders.task_store_of(old_folder) is None
    legacy = stored(old_folder, "pastes", "ab12cd34-legacy.txt")
    own_id(storage)
    assert task_sweep.sweep_all(storage) == 0 and legacy.exists()


def test_a_store_that_has_no_id_yet_sweeps_nothing(store, storage, root):
    _, folder = make_task(store, root, "x", store_id="0f0f0f0f0f0f0f0f")
    theirs = stored(folder, "pastes", "ab12cd34-theirs.txt")
    with closing(storage.connect(False)) as conn:
        assert store_identity.read(conn) is None
    assert task_sweep.sweep_all(storage) == 0 and theirs.exists()


def test_the_store_id_is_stable_and_random(storage, tmp_path):
    first = own_id(storage)
    assert own_id(storage) == first and len(first) == 16 and first != own_id(WorkStorage(tmp_path / "other"))


def test_ensure_task_writes_the_id_into_a_new_marker_and_never_into_an_old_one(tmp_path):
    root = tmp_path / "tm"
    root.mkdir()
    fresh = task_folders.ensure_task(root, 1, "all", None, "fresh", store_id="aaaa")
    assert task_folders.task_store_of(fresh) == "aaaa"
    old = task_folders.ensure_task(root, 2, "all", None, "old")
    assert task_folders.ensure_task(root, 2, "all", None, "old", store_id="aaaa") == old
    assert task_folders.task_store_of(old) is None


def second_store(tmp_path: Path) -> Tuple[WorkStorage, TaskManagerStore, int, str]:
    other = WorkStorage(tmp_path / "other")
    other_store = TaskManagerStore(other, notify=lambda t: None)
    return other, other_store, other_store.add("all", "task", actor="joe")["id"], own_id(other)


def paste_and_name(store: TaskManagerStore, item: int, folder: Path) -> Path:
    task_folders.kind_dir(folder, "pastes")
    path = stored(folder, "pastes", "ab12cd34-b-shot.png")
    entry = {"id": "ab12cd34", "name": "b-shot.png", "mime": "image/png", "size": 5, "path": str(path)}
    store.post(item, "b", actor="joe", parts=files.parts_of([entry]))
    return path


def test_two_stores_with_the_same_item_id_never_share_a_folder(store, storage, root, tmp_path):
    item_a, folder_a = make_task(store, root, "task")
    _, other_store, item_b, id_b = second_store(tmp_path)
    assert item_a == item_b == 1
    folder_b = task_folders.ensure_task(root, item_b, "all", None, "task", store_id=id_b)
    assert folder_b != folder_a and task_folders.task_store_of(folder_b) == id_b
    assert task_folders.ensure_task(root, item_b, "all", None, "task", store_id=id_b) == folder_b
    assert task_folders.ensure_task(root, item_a, "all", None, "task", store_id=own_id(storage)) == folder_a
    theirs = paste_and_name(other_store, item_b, folder_b)
    assert task_sweep.sweep_all(storage) == 0 and theirs.exists()


def test_a_store_never_claims_another_stores_legacy_folder(store, storage, root, tmp_path):
    other, other_store, item_b, _ = second_store(tmp_path)
    legacy = task_folders.ensure_task(root, item_b, "all", None, "task")
    theirs = paste_and_name(other_store, item_b, legacy)
    item_a = store.add("all", "task", actor="joe")["id"]
    assert item_a == item_b
    used = task_folders.ensure_task(root, item_a, "all", None, "task", store_id=own_id(storage))
    assert used == legacy and task_folders.task_store_of(legacy) is None
    assert task_sweep.sweep_all(storage) == 0 and theirs.exists()


def test_a_write_with_no_store_id_never_lands_in_a_stamped_folder(store, storage, root, tmp_path):
    other, other_store, item_b, id_b = second_store(tmp_path)
    folder_b = task_folders.ensure_task(root, item_b, "all", None, "task", store_id=id_b)
    item_a = store.add("all", "task", actor="joe")["id"]
    assert task_folders.find_task(root, item_a) is None
    folder_a = task_folders.ensure_task(root, item_a, "all", None, "task")
    assert folder_a != folder_b and task_folders.task_store_of(folder_a) is None
    assert task_folders.ensure_task(root, item_a, "all", None, "task") == folder_a
    mine = paste_and_name(store, item_a, folder_a)
    assert task_sweep.sweep_task_folders(other, root) == 0 and mine.exists()


def test_a_write_with_no_store_id_uses_an_unstamped_folder_before_making_one(tmp_path):
    root = tmp_path / "tm"
    root.mkdir()
    legacy = task_folders.ensure_task(root, 3, "all", None, "legacy")
    task_folders.ensure_task(root, 4, "all", None, "other", store_id="0f0f0f0f0f0f0f0f")
    assert task_folders.ensure_task(root, 3, "all", None, "legacy") == legacy
    assert task_folders.find_task(root, 4) is None and task_folders.find_task(root, 4, "0f0f0f0f0f0f0f0f") is not None


def test_a_hard_delete_with_a_known_store_id_removes_only_its_own_stamped_folder(store, storage, root):
    from src.cplugs.huddle import moves

    ports.register(task_folders.ROOT_PORT, FakeRoot(root))
    try:
        item = store.add("all", "mine", actor="joe")["id"]
        mine_id = own_id(storage)
        legacy = task_folders.ensure_task(root, item, "all", None, "mine")
        task_folders.kind_dir(legacy, "pastes")
        theirs = stored(legacy, "pastes", "ab12cd34-b-shot.png")
        assert moves.remove_task_files(item, mine_id) == 0 and theirs.exists()
    finally:
        ports.unregister(task_folders.ROOT_PORT)
