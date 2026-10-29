
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

import pytest

from src.cplugs.crate import project_git
from src.cplugs.devwidgetlab.drafts import checkout, ship, store
from src.cplugs.devwidgetlab.errors import DraftInvalid
from src.cplugs.huddle import wait_checks
from src.cplugs.runtime import git_ops, guards
from src.cplugs.runtime.dispatch import HostDispatcher


def _boom(*_a: Any, **_k: Any) -> Any:
    raise AssertionError("git was spawned although git_guard said it is unavailable")


@pytest.fixture(autouse=True)
def no_git(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.core.dev_tools.git_guard.git_available", lambda: False)
    monkeypatch.setattr("src.core.dev_tools.git_guard.usr_bin_git_available", lambda: False)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)


def test_wait_check_git_contains_is_unknown(tmp_path: Path) -> None:
    check = wait_checks.GitContains(kind="git_contains", repo=str(tmp_path), ref="HEAD", sha="a" * 40)
    verdict = wait_checks.check_git(check, roots=[tmp_path.resolve()])
    assert verdict.status == wait_checks.UNKNOWN and verdict.what == wait_checks.NO_GIT


def test_wait_check_roots_are_just_the_root(tmp_path: Path) -> None:
    assert wait_checks.app_repo_roots(tmp_path) == [tmp_path.resolve()]


def test_draft_head_sha_and_checkout_git_are_empty(tmp_path: Path) -> None:
    assert store.head_sha(tmp_path) == ""
    assert checkout.worktrees(tmp_path) == []


def test_ship_changed_since_is_false_and_git_raises_invalid(tmp_path: Path) -> None:
    assert ship._changed_since(tmp_path, "a" * 40, "x") is False
    with pytest.raises(DraftInvalid):
        ship._git(tmp_path, "status")


def test_crate_project_snapshot_is_none(tmp_path: Path) -> None:
    assert project_git.snapshot(str(tmp_path)) is None


def test_runtime_git_ops_refuse(tmp_path: Path) -> None:
    with pytest.raises(git_ops.GitRefused):
        git_ops.refuse_unsafe_config(tmp_path)
    with pytest.raises(git_ops.GitUnavailable):
        git_ops._run(["git", "status"])


@pytest.mark.parametrize("method", ["_projects_git", "_projects_snapshot"])
def test_dispatch_answers_unavailable_not_invalid_params_without_git(method: str, tmp_path: Path) -> None:
    dispatcher = HostDispatcher.__new__(HostDispatcher)
    dispatcher._need = lambda ctx, perm: None  # type: ignore[method-assign]
    dispatcher._repo = lambda project: tmp_path  # type: ignore[method-assign]
    params = {"project": 1, "op": "status", "turn": "t1"}
    with pytest.raises(guards.Refused) as caught:
        asyncio.run(getattr(dispatcher, method)(None, params))
    assert caught.value.code == "unavailable"


def test_git_on_path_but_a_shim_at_usr_bin_still_refuses_git_ops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.core.dev_tools.git_guard.git_available", lambda: True)
    monkeypatch.setattr("src.core.dev_tools.git_guard.usr_bin_git_available", lambda: False)
    with pytest.raises(git_ops.GitUnavailable):
        git_ops._run(["git", "status"])
    with pytest.raises(git_ops.GitUnavailable):
        git_ops.refuse_unsafe_config(tmp_path)
