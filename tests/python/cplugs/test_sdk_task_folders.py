
from __future__ import annotations

import json
import stat
from pathlib import Path

from src.cplugs.sdk import task_folders as tf


def test_names_are_the_slug_plus_the_id():
    assert tf.project_folder_name("18", "Carnivore") == "carnivore-18"
    assert tf.task_folder_name(592, "Alex: watch what Alex changed!") == "alex-watch-what-alex-changed-592"
    assert tf.project_folder_name("all", None) == tf.project_folder_name("agent:3", "Bob") == "no-project"
    assert tf.task_folder_name(7, "   ") == "task-7" and tf.project_folder_name("4", None) == "project-4"
    assert len(tf.task_folder_name(1, "x" * 500)) <= tf.MAX_SLUG + 2
    long = tf.slugify("Task Manager rebuild, Part 2: review board panel on the right", "task")
    assert long == "task-manager-rebuild-part-2-review-board-panel" and len(long) <= tf.MAX_SLUG


def test_the_layout_is_project_then_task(tmp_path: Path):
    task = tf.ensure_task(tmp_path, 592, "18", "Carnivore", "Alex: watch what Alex changed")
    assert task == tmp_path / "carnivore-18" / "alex-watch-what-alex-changed-592"
    assert tf.read_marker(task, tf.TASK_MARKER)["item_id"] == 592
    assert tf.read_marker(task.parent, tf.PROJECT_MARKER)["list"] == "18"
    personal = tf.ensure_task(tmp_path, 3, "all", None, "groceries")
    assert personal == tmp_path / "no-project" / "groceries-3"
    assert tf.ensure_task(tmp_path, 4, "agent:2", None, "agent work").parent == tmp_path / "no-project"


def test_a_folder_is_never_moved_by_a_rename_or_a_list_move(tmp_path: Path):
    first = tf.ensure_task(tmp_path, 592, "18", "Carnivore", "first title")
    assert tf.ensure_task(tmp_path, 592, "18", "Carnivore Renamed", "second title") == first
    assert tf.ensure_task(tmp_path, 592, "19", "Blog", "third title") == first
    assert tf.ensure_project(tmp_path, "18", "Carnivore Renamed") == tmp_path / "carnivore-18"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["carnivore-18"]


def test_a_look_alike_without_a_marker_or_through_a_symlink_is_never_used(tmp_path: Path):
    (tmp_path / "20261013-fix-18").mkdir()
    project = tf.ensure_project(tmp_path, "18", "Carnivore")
    assert project == tmp_path / "carnivore-18"
    (project / "lookalike-592").mkdir()
    real = tf.ensure_task(tmp_path, 592, "18", "Carnivore", "real")
    assert real == project / "real-592"
    elsewhere = tmp_path.parent / f"{tmp_path.name}-outside-9"
    elsewhere.mkdir()
    (elsewhere / tf.TASK_MARKER).write_text(json.dumps({"item_id": 9}))
    (project / "linked-9").symlink_to(elsewhere)
    assert tf.find_task(tmp_path, 9) is None and tf.ensure_task(tmp_path, 9, "18", None, "own") == project / "own-9"


def test_pastes_and_artifacts_are_private_and_git_ignored_boards_are_not(tmp_path: Path):
    task = tf.ensure_task(tmp_path, 1, "18", "c", "t")
    for kind in (tf.PASTES, tf.ARTIFACTS):
        folder = tf.kind_dir(task, kind)
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700 and (folder / ".gitignore").read_text() == "*\n"
    boards = tf.kind_dir(task, tf.BOARDS)
    assert not (boards / ".gitignore").exists()
    assert tf.kind_dir(task, tf.PASTES, create=False) == task / "pastes"
    assert [t.name for t in tf.task_folders(tmp_path)] == ["t-1"]
