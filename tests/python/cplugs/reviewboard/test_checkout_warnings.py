
from __future__ import annotations

from pathlib import Path
from typing import Any, List

import pytest

from src.cplugs.reviewboard import checkout, root as board_root

REMOTE = '[core]\n\tbare = false\n[remote "origin"]\n\turl = git@example.invalid:me/boards.git\n'


def make_checkout(tmp_path: Path, *, head: str = "ref: refs/heads/main\n", commit: bool = False, packed: bool = False,
                  config: str = "[core]\n\tbare = false\n") -> Path:
    git = tmp_path / "repo" / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text(head)
    (git / "config").write_text(config)
    if commit:
        (git / "refs" / "heads" / "main").write_text("a" * 40 + "\n")
    if packed:
        (git / "packed-refs").write_text("# pack-refs\n" + "b" * 40 + " refs/heads/main\n")
    boards = tmp_path / "repo" / "boards"
    boards.mkdir()
    (boards / ".boards-root").write_text("m")
    return boards


def codes(boards: Path) -> List[str]:
    return [w.code for w in checkout.warnings_for(boards)]


def test_a_bare_git_init_warns_about_commits_and_remote_and_stays_usable(tmp_path: Path) -> None:
    boards = make_checkout(tmp_path)
    assert codes(boards) == ["no_commits", "no_remote"]
    status = board_root.root_status(str(boards), tmp_path / "state")
    assert status.ok is True and status.path == str(boards) and [w.code for w in status.warnings] == ["no_commits", "no_remote"]


def test_a_committed_and_pushed_checkout_is_quiet(tmp_path: Path) -> None:
    assert codes(make_checkout(tmp_path, commit=True, config=REMOTE)) == []


def test_each_warning_stands_alone(tmp_path: Path) -> None:
    assert codes(make_checkout(tmp_path, commit=True)) == ["no_remote"]
    other = tmp_path / "b"
    other.mkdir()
    assert codes(make_checkout(other, config=REMOTE)) == ["no_commits"]


def test_packed_refs_and_a_detached_head_count_as_commits(tmp_path: Path) -> None:
    assert codes(make_checkout(tmp_path, packed=True, config=REMOTE)) == []
    other = tmp_path / "d"
    other.mkdir()
    assert codes(make_checkout(other, head="c" * 40 + "\n", config=REMOTE)) == []


def test_a_linked_worktree_reads_the_common_git_folder(tmp_path: Path) -> None:
    main = make_checkout(tmp_path, commit=True, config=REMOTE)
    worktree = tmp_path / "wt"
    (worktree / "boards").mkdir(parents=True)
    git_dir = tmp_path / "repo" / ".git" / "worktrees" / "wt"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    (git_dir / "commondir").write_text("../..\n")
    (worktree / ".git").write_text(f"gitdir: {git_dir}\n")
    assert main.is_dir() and codes(worktree / "boards") == []


def test_an_unreadable_checkout_says_nothing(tmp_path: Path) -> None:
    lone = tmp_path / "wt" / "boards"
    lone.mkdir(parents=True)
    (tmp_path / "wt" / ".git").write_text("gitdir: /does/not/exist\n")
    assert codes(lone) == []
    empty = tmp_path / "e" / "boards"
    empty.mkdir(parents=True)
    (tmp_path / "e" / ".git").mkdir()
    assert codes(empty) == []
    assert codes(tmp_path) == []


def test_the_status_reads_files_and_never_runs_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    def boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("a git process was started")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    assert codes(make_checkout(tmp_path)) == ["no_commits", "no_remote"]
