from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path
from typing import List

import pytest

from src.core.worktrees import cleanup, launch
from src.core.worktrees.store import WorktreeStore

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t"}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env=_ENV).stdout.strip()


def test_worktree_cleanup_rules(tmp_path: Path) -> None:
    async def run() -> None:
        repo = tmp_path / "app"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        (repo / "README").write_text("x")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "init")
        repo = Path(os.path.realpath(repo))
        state, root = tmp_path / "state", str(tmp_path / "wt")
        store = WorktreeStore(state)

        async def make(branch: str) -> str:
            return (await launch.prepare(str(repo), branch, "main", False, [], root=root, store=store,
                                         state_dir=state)).path

        merged, dirty, unmerged, gone = (await make("wt/merged"), await make("wt/dirty"), await make("wt/unmerged"),
                                         await make("wt/gone"))
        (Path(unmerged) / "new.txt").write_text("y")
        _git(Path(unmerged), "add", "-A")
        _git(Path(unmerged), "commit", "-q", "-m", "work")
        (Path(dirty) / "README").write_text("changed")
        _git(repo, "worktree", "add", "-q", str(tmp_path / "byhand"), "-b", "byhand")
        shutil.rmtree(gone)

        stopped: List[str] = []
        archived: List[str] = []

        async def stop(path: str) -> None:
            stopped.append(path)

        async def archive(path: str) -> None:
            archived.append(path)

        with pytest.raises(cleanup.CleanupRefused) as hand:
            await cleanup.plan(store, [str(tmp_path / "byhand")])
        assert hand.value.code == "not_offered"
        everything = await cleanup.plan(store)
        assert str(tmp_path / "byhand") not in [w["path"] for w in everything["worktrees"]]
        finished = await cleanup.plan(store, finished_only=True)
        assert sorted(w["path"] for w in finished["worktrees"]) == sorted([merged, gone])

        targets = [merged, dirty, unmerged, gone]
        seen = await cleanup.plan(store, targets)
        (Path(merged) / "late.txt").write_text("z")
        with pytest.raises(cleanup.CleanupRefused) as stale:
            await cleanup.apply(store, targets, seen["fingerprint"], stop=stop, archive=archive)
        assert stale.value.code == "fingerprint_stale" and not stopped and os.path.isdir(merged)
        os.remove(Path(merged) / "late.txt")

        seen = await cleanup.plan(store, targets)
        result = {r["path"]: r for r in (await cleanup.apply(store, targets, seen["fingerprint"], stop=stop,
                                                              archive=archive))["removed"]}
        assert result[merged]["removed"] and result[merged]["branch_deleted"] and not os.path.exists(merged)
        assert result[dirty]["removed"] is False and result[dirty]["error"] and os.path.isdir(dirty)
        assert result[unmerged]["removed"] and not result[unmerged]["branch_deleted"]
        assert "wt/unmerged" in _git(repo, "branch", "--list", "wt/unmerged")
        assert result[gone]["removed"] and result[gone]["branch_deleted"]
        assert sorted(archived) == sorted([merged, unmerged, gone]) and set(stopped) == set(targets)
        assert [r.path for r in store.live()] == [dirty]

    asyncio.run(run())


def test_a_change_made_while_the_agent_stops_is_never_forced_away(tmp_path: Path) -> None:
    async def run() -> None:
        repo = tmp_path / "app"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        (repo / "README").write_text("x")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "init")
        repo = Path(os.path.realpath(repo))
        state, root = tmp_path / "state", str(tmp_path / "wt")
        store = WorktreeStore(state)
        path = (await launch.prepare(str(repo), "wt/busy", "main", False, [], root=root, store=store,
                                     state_dir=state)).path
        (Path(path) / "README").write_text("shown in the plan")

        async def stop(where: str) -> None:
            (Path(where) / "last-words.txt").write_text("the agent's final write")

        async def archive(where: str) -> None:
            raise AssertionError("archived a worktree that changed")

        seen = await cleanup.plan(store, [path])
        result = (await cleanup.apply(store, [path], seen["fingerprint"], stop=stop, archive=archive,
                                      remove_dirty=True))["removed"][0]
        assert result["removed"] is False and result["error"]
        assert (Path(path) / "last-words.txt").read_text() == "the agent's final write"
        assert [r.path for r in store.live()] == [path]

    asyncio.run(run())


def test_a_launch_that_reuses_a_hand_made_worktree_does_not_make_it_cleanups(tmp_path: Path) -> None:
    async def run() -> None:
        repo = tmp_path / "app"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        (repo / "README").write_text("x")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "init")
        repo = Path(os.path.realpath(repo))
        state, root = tmp_path / "state", tmp_path / "wt"
        byhand = root / "app" / "feat-x"
        _git(repo, "worktree", "add", "-q", str(byhand), "-b", "feat/x")
        store = WorktreeStore(state)
        done = await launch.prepare(str(repo), "feat/x", "main", False, [], root=str(root), store=store,
                                    state_dir=state)
        assert done.created is False and done.path == os.path.realpath(byhand)
        assert store.live() == []

    asyncio.run(run())
