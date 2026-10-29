
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from src.core.work.file_refs import FileHome
from src.cplugs.sdk import task_folders

ID = "abcd1234"
NAME = f"{ID}-a.png"


def make_task(root: Path, item: Optional[int] = 5, kind: str = "pastes") -> Path:
    task = root / "p-1" / "t-5"
    (task / kind).mkdir(parents=True)
    if item is not None:
        (task / ".tm-task").write_text(json.dumps({"item_id": item}))
    (task / kind / NAME).write_bytes(b"bytes")
    return task / kind / NAME


def problem(path: Path, root: Path, item_id: Optional[int] = None) -> Optional[str]:
    return task_folders.task_file_problem(path, [root], ID, item_id)


def test_a_marked_task_file_under_the_root_is_accepted(tmp_path: Path) -> None:
    assert problem(make_task(tmp_path), tmp_path, 5) is None


def test_a_file_outside_pastes_and_artifacts_is_refused(tmp_path: Path) -> None:
    assert problem(make_task(tmp_path, kind="boards"), tmp_path) == "it is not in a pastes or artifacts folder"


def test_a_symlinked_file_is_refused(tmp_path: Path) -> None:
    real = make_task(tmp_path)
    link = real.with_name(f"{ID}-link.png")
    os.symlink(real, link)
    assert problem(link, tmp_path) == "it is not a regular file (or is a link)"


def test_a_symlinked_pastes_folder_is_refused(tmp_path: Path) -> None:
    task = tmp_path / "p-1" / "t-5"
    (task / "real").mkdir(parents=True)
    (task / ".tm-task").write_text(json.dumps({"item_id": 5}))
    (task / "real" / NAME).write_bytes(b"x")
    os.symlink(task / "real", task / "pastes")
    assert problem(task / "pastes" / NAME, tmp_path) == "its folder is a link"


def test_a_file_outside_the_configured_root_is_refused(tmp_path: Path) -> None:
    elsewhere = make_task(tmp_path / "elsewhere")
    root = tmp_path / "configured"
    root.mkdir()
    assert problem(elsewhere, root) == "it lies outside the Task Manager folder"
    assert task_folders.task_file_problem(elsewhere, [], ID) == "no Task Manager folder is set"


def test_a_symlinked_folder_that_leads_out_is_refused(tmp_path: Path) -> None:
    outside = make_task(tmp_path / "outside")
    root = tmp_path / "configured"
    root.mkdir()
    os.symlink(tmp_path / "outside" / "p-1", root / "p-1")
    assert problem(root / "p-1" / "t-5" / "pastes" / outside.name, root) == "it lies outside the Task Manager folder"


def test_a_folder_without_a_task_marker_is_refused(tmp_path: Path) -> None:
    assert problem(make_task(tmp_path, item=None), tmp_path) == "its folder is not a task folder"


def test_a_marker_naming_another_item_is_refused(tmp_path: Path) -> None:
    path = make_task(tmp_path, item=5)
    assert problem(path, tmp_path, 6) == "its folder belongs to another task"
    assert problem(path, tmp_path) is None


def test_file_home_copies_a_good_source_and_refuses_each_bad_one(tmp_path: Path) -> None:
    root = tmp_path / "tm"
    good = make_task(root)
    evil = tmp_path / "evil"
    evil.mkdir()
    (evil / f"{ID}-secret.txt").write_bytes(b"outside")
    task = root / "p-2" / "t-9"
    task.mkdir(parents=True)
    (task / ".tm-task").write_text(json.dumps({"item_id": 9}))
    os.symlink(evil, task / "pastes")
    home = FileHome(tmp_path / "state", roots=[root])
    doc = {"files": [{"id": ID, "name": "a.png", "path": str(good)},
                     {"id": ID, "name": "secret.txt", "path": str(task / "pastes" / f"{ID}-secret.txt")}]}
    home.rewrite(doc, 1, 2)
    assert [e["path"] for e in doc["files"]] == [f"files/2/{NAME}"] and home.dropped == ["secret.txt"]
    assert list(home.copied) == [str(tmp_path / "state" / "cplugs" / "huddle" / "files" / "2" / NAME)]
