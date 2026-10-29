
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest

from src.core.pack.migrate import manifest as manifest_mod
from src.core.pack.migrate import task_manager_history, task_manager_side
from src.cplugs.sdk import ports, task_folders
from tests.python.pack.test_task_manager_side_compat import ITEM_INSERT, machine, sql

FILE_ID = "abcd1234"
NAME = f"{FILE_ID}-shot.png"
BYTES = b"\x89PNG task file bytes"


class FakeRoot:

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def root(self) -> Path:
        return self.folder


@pytest.fixture(autouse=True)
def task_manager_folder(tmp_path: Path) -> Iterator[Path]:
    folder = tmp_path / "tm"
    folder.mkdir()
    ports.register(task_folders.ROOT_PORT, FakeRoot(folder))
    yield folder
    ports.unregister(task_folders.ROOT_PORT)


def task_folder(tmp_path: Path, *, marker: bool = True) -> Path:
    folder = tmp_path / "tm" / "p-1" / "t-5"
    (folder / "pastes").mkdir(parents=True)
    if marker:
        (folder / ".tm-task").write_text(json.dumps({"item_id": 5}))
    paste = folder / "pastes" / NAME
    paste.write_bytes(BYTES)
    return paste


def entry_for(path: str, name: str = "shot.png") -> Dict[str, Any]:
    return {"id": FILE_ID, "name": name, "mime": "image/png", "size": len(BYTES), "path": path}


def exported_with(tmp_path: Path, entries: List[Dict[str, Any]], text: str = "see file") -> Dict[str, Any]:
    source = machine(tmp_path, "a")
    for n, entry in enumerate(entries, 1):
        sql(source, ITEM_INSERT, ("16", f"item {n}", "", n, "open"))
        sql(source, "INSERT INTO work_messages (item_id, author, kind, text, created_at, seq, parts) VALUES (?, 'joe', 'say', ?, 1, ?, ?)",
            (n, text, n, json.dumps({"files": [entry]})))
    return json.loads(json.dumps(task_manager_side.export_list(source, "16")))


def source_with_two_items(tmp_path: Path, paste: Path) -> Dict[str, Any]:
    return exported_with(tmp_path, [entry_for(str(paste)), entry_for(str(paste))])


def parts_of(state: str) -> List[Dict[str, Any]]:
    return [{"item_id": r["item_id"], "path": e["path"]} for r in sql(state, "SELECT item_id, parts FROM work_messages ORDER BY id")
            for e in json.loads(r["parts"] or '{"files": []}')["files"]]


def test_two_items_that_named_one_file_each_get_their_own_copy(tmp_path: Path):
    paste = task_folder(tmp_path)
    target = machine(tmp_path, "b")
    task_manager_side.import_list(target, "4", source_with_two_items(tmp_path, paste), {})
    refs = parts_of(target)
    assert len(refs) == 2 and refs[0]["path"] != refs[1]["path"]
    for ref in refs:
        assert ref["path"] == f"files/{ref['item_id']}/{NAME}", "the path is the receiving item's own folder, not the source's absolute path"
        assert (Path(target) / "cplugs" / "huddle" / ref["path"]).read_bytes() == BYTES
    assert paste.read_bytes() == BYTES, "the source file is never touched"


def test_deleting_one_items_copy_leaves_the_other_item_s_file(tmp_path: Path):
    paste = task_folder(tmp_path)
    target = machine(tmp_path, "b")
    task_manager_side.import_list(target, "4", source_with_two_items(tmp_path, paste), {})
    first, second = parts_of(target)
    (Path(target) / "cplugs" / "huddle" / first["path"]).unlink()
    assert (Path(target) / "cplugs" / "huddle" / second["path"]).read_bytes() == BYTES


def test_undo_removes_exactly_the_copies(tmp_path: Path):
    paste = task_folder(tmp_path)
    target = machine(tmp_path, "b")
    record = task_manager_side.import_list(target, "4", source_with_two_items(tmp_path, paste), {})
    assert len(record["task_files"]) == 2 and all(Path(p).is_file() for p in record["task_files"])
    task_manager_side.undo(target, "4", record)
    assert not any(Path(p).exists() for p in record["task_files"])
    assert not any(Path(p).parent.exists() for p in record["task_files"]), "the emptied item folders go too"
    assert paste.read_bytes() == BYTES


def test_undo_keeps_a_copy_the_owner_changed(tmp_path: Path):
    paste = task_folder(tmp_path)
    target = machine(tmp_path, "b")
    record = task_manager_side.import_list(target, "4", source_with_two_items(tmp_path, paste), {})
    changed, untouched = (Path(p) for p in record["task_files"])
    changed.write_bytes(b"the owner edited this")
    task_manager_side.undo(target, "4", record)
    assert changed.read_bytes() == b"the owner edited this" and not untouched.exists()


def test_a_file_that_is_not_a_task_file_is_dropped_never_copied_and_the_message_says_so(tmp_path: Path):
    paste = task_folder(tmp_path, marker=False)
    outside = tmp_path / "secret.txt"
    outside.write_text("not for the thread")
    target = machine(tmp_path, "b")
    record = task_manager_side.import_list(target, "4", exported_with(tmp_path, [entry_for(str(paste)), entry_for(str(outside), "secret.txt")]), {})
    assert parts_of(target) == [] and not record["task_files"] and sorted(record["task_files_dropped"]) == ["secret.txt", "shot.png"]
    texts = sorted(r["text"] for r in sql(target, "SELECT text FROM work_messages"))
    assert texts == ["see file\n[secret.txt was not on this computer]", "see file\n[shot.png was not on this computer]"]
    assert not (Path(target) / "cplugs" / "huddle" / "files").exists()


def test_a_files_only_message_is_never_left_an_empty_bubble(tmp_path: Path):
    target = machine(tmp_path, "b")
    manifest = exported_with(tmp_path, [entry_for("/nowhere/t/pastes/" + NAME, "x.png")], text="")
    task_manager_side.import_list(target, "4", manifest, {})
    row = sql(target, "SELECT text, parts FROM work_messages")[0]
    assert row["text"] == "[x.png was not on this computer]" and row["parts"] == ""


def test_a_relative_path_is_dropped_because_pack_carries_no_bytes(tmp_path: Path):
    target = machine(tmp_path, "b")
    manifest = exported_with(tmp_path, [entry_for(f"files/1/{NAME}", "x.png")])
    other = Path(target) / "cplugs" / "huddle" / "files" / "1"
    other.mkdir(parents=True)
    (other / NAME).write_bytes(b"a local item's own file")
    record = task_manager_side.import_list(target, "4", manifest, {})
    assert parts_of(target) == [] and record["task_files_dropped"] == ["x.png"] and not record["task_files"]
    assert "[x.png was not on this computer]" in sql(target, "SELECT text FROM work_messages")[0]["text"]


def test_any_failure_after_the_copies_removes_them(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    paste = task_folder(tmp_path)
    manifest = source_with_two_items(tmp_path, paste)
    target = machine(tmp_path, "b")

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise ValueError("bad history row")

    monkeypatch.setattr(task_manager_history, "import_into", boom)
    with pytest.raises(ValueError):
        task_manager_side.import_list(target, "4", manifest, {})
    assert list(Path(target).rglob(NAME)) == [] and sql(target, "SELECT COUNT(*) AS n FROM work_messages")[0]["n"] == 0


def test_the_migrate_summary_names_the_files_that_were_not_copied(tmp_path: Path):
    target = machine(tmp_path, "b")
    manifest = {"project": {}, "company": None, "sessions": [], "agents": [], "agent_files": {},
                "huddle": exported_with(tmp_path, [entry_for("/nowhere/t/pastes/" + NAME, "x.png")])}
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, company_id INTEGER)")
    conn.execute("INSERT INTO projects (id) VALUES (4)")
    conn.commit()
    summary = manifest_mod.apply(conn, manifest, project_id=4, target_root=str(tmp_path / "root"), state_dir=target, undo={})
    assert summary["task_files_not_copied"] == ["x.png"] and summary["messages"] == 1
