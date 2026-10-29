
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.core.session_move import files as mf


def _temp_folder(root: Path) -> Path:
    src = root / "ses_ab12"
    (src / "src" / "deep").mkdir(parents=True)
    (src / "empty").mkdir()
    (src / "notes.md").write_text("hello", encoding="utf-8")
    (src / "src" / "deep" / "app.py").write_text("print(1)\n", encoding="utf-8")
    (src / ".cc.theme").write_text("matrix", encoding="utf-8")
    os.symlink("notes.md", src / "link.md")
    return src


def test_inventory_lists_files_and_links_and_leaves_the_theme(tmp_path: Path) -> None:
    inv = mf.inventory(_temp_folder(tmp_path))
    assert set(inv.files) == {"notes.md", os.path.join("src", "deep", "app.py"), "link.md"}
    assert inv.files["notes.md"] == 5
    assert ".cc.theme" in inv.left_behind and ".cc.theme" not in inv.files
    assert "empty" in inv.dirs


def test_a_same_name_file_is_a_collision_but_folders_merge(tmp_path: Path) -> None:
    inv = mf.inventory(_temp_folder(tmp_path))
    dest = tmp_path / "app"
    (dest / "src").mkdir(parents=True)
    (dest / "src" / "other.py").write_text("x", encoding="utf-8")
    assert mf.collisions(inv, dest) == []
    (dest / "notes.md").write_text("theirs", encoding="utf-8")
    assert mf.collisions(inv, dest) == ["notes.md"]


def test_both_git_folders_are_detected(tmp_path: Path) -> None:
    src, dest = tmp_path / "ses_x", tmp_path / "app"
    (src / ".git").mkdir(parents=True)
    dest.mkdir()
    assert not mf.both_git(src, dest)
    (dest / ".git").mkdir()
    assert mf.both_git(src, dest)


def test_backup_then_move_carries_every_file_and_verifies_the_count(tmp_path: Path) -> None:
    src = _temp_folder(tmp_path)
    inv = mf.inventory(src)
    dest = tmp_path / "app"
    dest.mkdir()
    backup = mf.backup(src, inv, tmp_path / "state" / "session-moves" / "u" / "t", {"destination": str(dest)})
    moved = mf.move_files(src, dest, inv)
    assert len(moved) == len(inv.files) == 3
    assert mf.verify_moved(src, dest, inv) == []
    assert (dest / "src" / "deep" / "app.py").read_text(encoding="utf-8") == "print(1)\n"
    assert os.path.islink(dest / "link.md")
    assert (dest / "empty").is_dir()
    assert all(os.path.lexists(backup / "files" / rel) for rel in inv.files)
    assert (src / ".cc.theme").exists() and not (dest / ".cc.theme").exists()
    assert not (src / "src").exists()


def test_a_file_appearing_mid_move_puts_every_moved_file_back(tmp_path: Path) -> None:
    src = _temp_folder(tmp_path)
    inv = mf.inventory(src)
    dest = tmp_path / "app"
    dest.mkdir()
    (dest / "notes.md").write_text("arrived late", encoding="utf-8")
    with pytest.raises(mf.SessionMoveFilesError) as caught:
        mf.move_files(src, dest, inv)
    assert caught.value.undo_errors == []
    assert set(mf.inventory(src).files) == set(inv.files)
    assert (dest / "notes.md").read_text(encoding="utf-8") == "arrived late"
    assert not os.path.lexists(dest / "link.md")


def test_verify_names_a_file_that_did_not_arrive(tmp_path: Path) -> None:
    src = _temp_folder(tmp_path)
    inv = mf.inventory(src)
    dest = tmp_path / "app"
    dest.mkdir()
    mf.move_files(src, dest, inv)
    os.unlink(dest / "notes.md")
    assert mf.verify_moved(src, dest, inv) == ["notes.md"]
