
from __future__ import annotations

from pathlib import Path

import pytest

from src.cplugs.huddle import files, store_identity
from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.storage import WorkStorage
from src.cplugs.sdk import ports, task_folders


class FakeRoot:

    def __init__(self, folder: Path):
        self.folder = folder

    def root(self) -> Path:
        return self.folder


@pytest.fixture
def store(tmp_path: Path) -> TaskManagerStore:
    return TaskManagerStore(WorkStorage(tmp_path / "state"), notify=lambda t: None)


@pytest.fixture
def root(tmp_path: Path):
    folder = tmp_path / "tm"
    folder.mkdir()
    ports.register(task_folders.ROOT_PORT, FakeRoot(folder))
    yield folder
    ports.unregister(task_folders.ROOT_PORT)


def name_files(store, item_id: int, *paths: Path) -> None:
    entries = [{"id": f"{n:08x}", "name": p.name, "mime": "text/plain", "size": 1, "path": str(p)} for n, p in enumerate(paths, 1)]
    store.post(item_id, "files", actor="joe", parts=files.parts_of(entries))


def task_with_files(store, root: Path, text: str) -> tuple:
    item = store.add("all", text, actor="joe")
    folder = task_folders.ensure_task(root, item["id"], "all", None, text)
    for kind in (task_folders.PASTES, task_folders.ARTIFACTS, task_folders.BOARDS):
        (task_folders.kind_dir(folder, kind) / "f.txt").write_text("x")
    name_files(store, item["id"], folder / "pastes" / "f.txt", folder / "artifacts" / "f.txt")
    return item["id"], folder


def test_hard_delete_removes_pastes_and_artifacts_only_for_that_item(store, root):
    gone_id, gone = task_with_files(store, root, "gone")
    _, other = task_with_files(store, root, "other")
    store.delete(gone_id, actor="joe")
    assert not (gone / "pastes").exists() and not (gone / "artifacts").exists()
    assert (gone / "boards" / "f.txt").exists()
    assert (other / "pastes" / "f.txt").exists() and (other / "artifacts" / "f.txt").exists()


def test_hard_delete_survives_a_missing_task_folder_and_no_root(store, tmp_path):
    item = store.add("all", "plain", actor="joe")
    assert store.delete(item["id"], actor="joe")["deleted"] is True
    ports.register(task_folders.ROOT_PORT, FakeRoot(tmp_path / "empty"))
    try:
        other = store.add("all", "two", actor="joe")
        assert store.delete(other["id"], actor="joe")["deleted"] is True
    finally:
        ports.unregister(task_folders.ROOT_PORT)


def test_soft_removal_keeps_files(store, root):
    item_id, folder = task_with_files(store, root, "done")
    store.update(item_id, actor="joe", approve=True)
    assert store.remove_completed("all", actor="joe")["removed"] == [item_id]
    assert (folder / "pastes" / "f.txt").exists()


def test_hard_delete_leaves_a_folder_another_store_stamped(store, root):
    item = store.add("all", "mine", actor="joe")
    theirs = task_folders.ensure_task(root, item["id"], "all", None, "mine", store_id="0f0f0f0f0f0f0f0f")
    (task_folders.kind_dir(theirs, task_folders.PASTES) / "f.txt").write_text("x")
    store.delete(item["id"], actor="joe")
    assert (theirs / "pastes" / "f.txt").exists()


def known_id(store) -> str:
    from contextlib import closing

    with closing(store._storage.connect(True)) as conn, conn:
        return store_identity.ensure(conn)


def test_hard_delete_removes_the_files_its_thread_names_from_an_unstamped_folder(store, root):
    known_id(store)
    item, folder = task_with_files(store, root, "legacy")
    (folder / "pastes" / "theirs.txt").write_text("b")
    store.delete(item, actor="joe")
    assert not (folder / "pastes" / "f.txt").exists() and not (folder / "artifacts" / "f.txt").exists()
    assert (folder / "pastes" / "theirs.txt").exists() and (folder / "boards" / "f.txt").exists()
    assert not (folder / "artifacts").exists()
    assert (folder / "pastes").exists() and folder.exists()


def test_hard_delete_takes_the_emptied_dirs_of_an_unstamped_folder_and_keeps_the_task_folder(store, root):
    known_id(store)
    item, folder = task_with_files(store, root, "all ours")
    store.delete(item, actor="joe")
    assert not (folder / "pastes").exists() and not (folder / "artifacts").exists()
    assert (folder / "boards" / "f.txt").exists() and (folder / task_folders.TASK_MARKER).exists()


def test_hard_delete_never_follows_a_symlink_or_leaves_the_folder(store, root, tmp_path):
    known_id(store)
    item, folder = task_with_files(store, root, "linked")
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    (folder / "pastes" / "f.txt").unlink()
    (folder / "pastes" / "f.txt").symlink_to(outside)
    store.delete(item, actor="joe")
    assert outside.read_text() == "keep" and (folder / "pastes" / "f.txt").is_symlink()


def test_a_folder_that_cannot_be_removed_keeps_its_gitignore(store, root, monkeypatch):
    known_id(store)
    item, folder = task_with_files(store, root, "raced")
    real = Path.rmdir

    def refuse(self):
        if self.name == "pastes":
            raise OSError(66, "Directory not empty")
        return real(self)

    monkeypatch.setattr(Path, "rmdir", refuse)
    store.delete(item, actor="joe")
    assert (folder / "pastes" / task_folders.GITIGNORE).read_bytes() == task_folders.GITIGNORE_BODY
    assert not (folder / "pastes" / "f.txt").exists() and not any(p.name.startswith(".") and "aside" in p.name for p in folder.iterdir())
