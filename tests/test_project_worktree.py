
from __future__ import annotations

import asyncio
import json
import os

import pytest

from tests.blueprints_helpers import git, make_repo

# ruff: noqa: E402
from src.core import project_worktree as pw


def _run(coro):
    return asyncio.run(coro)


def test_a_worktree_is_made_on_a_new_branch_under_the_root(tmp_path):
    repo = make_repo(tmp_path / "app")
    root = str(tmp_path / "wt")
    plan = _run(pw.plan_worktree(str(repo), "master", "feat/759-x", root=root))
    assert plan.path == os.path.realpath(tmp_path / "wt" / "app" / "feat-759-x")
    assert not plan.reuse and not plan.branch_exists
    assert _run(pw.create_worktree(plan, root=root)) is True
    assert git("-C", plan.path, "symbolic-ref", "--short", "HEAD") == "feat/759-x"


def test_a_second_plan_reuses_the_same_worktree(tmp_path):
    repo = make_repo(tmp_path / "app")
    root = str(tmp_path / "wt")
    first = _run(pw.plan_worktree(str(repo), "master", "feat/a", root=root))
    _run(pw.create_worktree(first, root=root))
    again = _run(pw.plan_worktree(str(repo), "master", "feat/a", root=root))
    assert again.reuse and _run(pw.create_worktree(again, root=root)) is False


@pytest.mark.parametrize("branch", ["feat..x", "x.lock", "a//b", "-x", "a@{b"])
def test_a_branch_git_refuses_is_refused_before_anything_is_written(tmp_path, branch):
    repo = make_repo(tmp_path / "app")
    with pytest.raises(pw.WorktreeRefused) as caught:
        _run(pw.plan_worktree(str(repo), "master", branch, root=str(tmp_path / "wt")))
    assert caught.value.code == "branch_invalid"
    assert not (tmp_path / "wt").exists()


def test_an_option_shaped_branch_never_reaches_git_as_an_option(tmp_path):
    marker = tmp_path / "pwned"
    with pytest.raises(pw.WorktreeRefused):
        _run(pw.check_branch_name(f"--upload-pack=touch {marker}"))
    assert not marker.exists()


def test_a_subdirectory_or_a_plain_folder_is_not_a_repository(tmp_path):
    repo = make_repo(tmp_path / "app")
    (repo / "sub").mkdir()
    (tmp_path / "plain").mkdir()
    for where in (repo / "sub", tmp_path / "plain"):
        with pytest.raises(pw.WorktreeRefused) as caught:
            _run(pw.plan_worktree(str(where), "master", "x", root=str(tmp_path / "wt")))
        assert caught.value.code == "not_a_repository"


def test_an_unknown_base_is_refused(tmp_path):
    repo = make_repo(tmp_path / "app")
    with pytest.raises(pw.WorktreeRefused) as caught:
        _run(pw.plan_worktree(str(repo), "nope", "x", root=str(tmp_path / "wt")))
    assert caught.value.code == "base_branch_unknown"


def test_a_symlink_planted_under_the_root_cannot_redirect_the_worktree(tmp_path):
    repo = make_repo(tmp_path / "app")
    root = tmp_path / "wt"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    root.mkdir()
    (root / "app").symlink_to(elsewhere)
    with pytest.raises(pw.WorktreeRefused) as caught:
        _run(pw.plan_worktree(str(repo), "master", "x", root=str(root)))
    assert caught.value.code == "worktree_path_escapes"
    assert list(elsewhere.iterdir()) == []


def test_a_root_inside_the_repository_is_refused(tmp_path):
    repo = make_repo(tmp_path / "app")
    with pytest.raises(pw.WorktreeRefused) as caught:
        _run(pw.plan_worktree(str(repo), "master", "x", root=str(repo / "trees")))
    assert caught.value.code == "worktree_path_escapes"


def test_something_else_at_the_target_is_never_overwritten(tmp_path):
    repo = make_repo(tmp_path / "app")
    target = tmp_path / "wt" / "app" / "x"
    target.mkdir(parents=True)
    (target / "keep.txt").write_text("mine")
    with pytest.raises(pw.WorktreeRefused) as caught:
        _run(pw.plan_worktree(str(repo), "master", "x", root=str(tmp_path / "wt")))
    assert caught.value.code == "worktree_path_taken"
    assert (target / "keep.txt").read_text() == "mine"


@pytest.mark.parametrize("root", ["/", "/etc", "relative/path", "~"])
def test_a_system_relative_or_home_root_is_refused(root):
    with pytest.raises(pw.WorktreeRefused) as caught:
        pw.resolve_root(root)
    assert caught.value.code == "worktree_root_invalid"


def test_the_root_is_stored_through_the_config_writer_and_read_back(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"other": {"keep": 1}}))
    assert pw.read_root(config) == pw.DEFAULT_ROOT
    pw.set_root(config, str(tmp_path / "trees"))
    assert pw.read_root(config) == str(tmp_path / "trees")
    assert json.loads(config.read_text())["other"] == {"keep": 1}


def test_a_git_call_past_its_bound_is_killed_and_reported(monkeypatch):
    real = asyncio.create_subprocess_exec

    async def slow(*_args, **kwargs):
        return await real("sleep", "5", stdout=kwargs.get("stdout"), stderr=kwargs.get("stderr"))

    monkeypatch.setattr(pw.asyncio, "create_subprocess_exec", slow)
    with pytest.raises(pw.WorktreeTimeout):
        _run(pw.run_git(["--version"], timeout=0.2))
