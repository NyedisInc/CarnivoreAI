
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

from src.core.crate_import import apply as ap
from src.core.crate_import import undo
from src.core.work import folders

DATA = b"a task file the old build imported"
REL = ("7", "ab12cd34-a.png")


def old_build_import(state: Path) -> Tuple[List[Dict[str, Any]], Path, Path]:
    old_root, new_root = (state.joinpath(*folders.files_rel(i).split("/")) for i in (folders.OLD_ID, folders.NEW_ID))
    old_root.mkdir(parents=True)
    old_file = old_root.joinpath(*REL)
    log = undo.creation_entries(old_file, old_root, hashlib.sha256(DATA).hexdigest(), len(DATA), {"task_files": True})
    old_file.parent.mkdir(parents=True)
    old_file.write_bytes(DATA)
    shutil.copytree(old_root, new_root)
    return log, old_file, new_root.joinpath(*REL)


def env_for(state: Path) -> SimpleNamespace:
    return SimpleNamespace(state=state, claude_homes=[], codex_home=state / "no-codex", plugin_homes=lambda p, d: None,
                           backup_dir=lambda i: state / "backups" / i)


def test_undo_of_an_old_import_removes_the_old_copy_then_the_new_one(tmp_path: Path) -> None:
    log, old_file, new_file = old_build_import(tmp_path)
    report = ap.recover_files(log, env_for(tmp_path))
    assert not old_file.exists() and not new_file.exists(), report
    assert not old_file.parent.exists() and not new_file.parent.exists()
    assert report.removed.index(str(old_file)) < report.removed.index(str(new_file)), "the old copy goes first"


def test_an_old_copy_the_owner_changed_keeps_both(tmp_path: Path) -> None:
    log, old_file, new_file = old_build_import(tmp_path)
    old_file.write_bytes(b"edited since")
    ap.recover_files(log, env_for(tmp_path))
    assert old_file.read_bytes() == b"edited since" and new_file.read_bytes() == DATA


def test_a_new_copy_the_owner_changed_stays(tmp_path: Path) -> None:
    log, old_file, new_file = old_build_import(tmp_path)
    new_file.write_bytes(b"edited in the new folder")
    ap.recover_files(log, env_for(tmp_path))
    assert not old_file.exists() and new_file.read_bytes() == b"edited in the new folder"
