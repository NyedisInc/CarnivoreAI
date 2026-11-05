from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.core import project_worktree
from src.core.project_lineage.parents import parent_project_ids
from src.core.worktrees import launch, repo_file
from src.core.worktrees.store import WorktreeStore

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t"})


def _repo(tmp: Path, setup: list) -> Path:
    repo = tmp / "app"
    (repo / ".carnivore").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README").write_text("x")
    (repo / ".carnivore" / "worktree.json").write_text(json.dumps({"setup": setup, "copy": [".env"]}))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    (repo / ".env").write_text("A=1\n")
    return Path(os.path.realpath(repo))


def test_worktree_launch_end_to_end(tmp_path: Path) -> None:
    async def run() -> None:
        state = tmp_path / "state"
        store = WorktreeStore(state)
        root = str(tmp_path / "wt")
        plain = tmp_path / "plain"
        plain.mkdir()
        assert await launch.probe(str(plain), store) == {"repo": False}

        repo = _repo(tmp_path, [["touch", "setup-ran"]])
        seen = await launch.probe(str(repo), store)
        assert seen["repo"] and seen["current"] == "main" and seen["file"]["approved"] is False
        assert seen["file"]["copy"] == [{"name": ".env", "secret": True}]

        with pytest.raises(repo_file.RepoFileRefused) as unapproved:
            await launch.prepare(str(repo), "feat/x", None, True, [], root=root, store=store, state_dir=state)
        assert unapproved.value.code == "setup_unapproved"

        os.symlink("/etc/hosts", repo / "linked")
        with pytest.raises(repo_file.RepoFileRefused) as linked:
            await launch.prepare(str(repo), "feat/x", None, False, ["linked"], root=root, store=store,
                                 state_dir=state)
        assert linked.value.code == "copy_refused"
        assert not os.path.exists(root) or not os.listdir(root), "a refusal must write nothing"

        store.approve(str(repo), seen["file"]["sha256"])
        done = await launch.prepare(str(repo), "feat/x", None, True, [".env"], root=root, store=store,
                                    state_dir=state)
        wt = Path(done.path)
        assert done.created and wt.is_dir() and (wt / ".env").read_text() == "A=1\n"
        assert (wt / "setup-ran").exists() and done.setup_log and Path(done.setup_log).exists()
        code, branch, _ = await project_worktree.run_git(["-C", str(wt), "symbolic-ref", "--short", "HEAD"])
        assert code == 0 and branch == "feat/x"
        assert store.repo_by_path() == {done.path: str(repo)}
        lineage = parent_project_ids([{"id": 1, "root": str(repo)}, {"id": 2, "root": done.path}],
                                     store.repo_by_path())
        assert lineage == {1: None, 2: 1}

        (repo / ".carnivore" / "worktree.json").write_text(json.dumps({"setup": [["touch", "other"]]}))
        with pytest.raises(repo_file.RepoFileRefused) as changed:
            await launch.prepare(str(repo), "feat/y", None, True, [], root=root, store=store, state_dir=state)
        assert changed.value.code == "setup_unapproved", "an edited file must ask again"

        with pytest.raises(repo_file.RepoFileRefused):
            (repo / ".carnivore" / "worktree.json").write_text(json.dumps({"setup": ["rm -rf /"]}))
            repo_file.read_repo_file(str(repo))

    asyncio.run(run())


def test_the_setup_budget_kills_what_a_step_started_too(tmp_path):
    import asyncio
    import os
    import time

    from src.core.worktrees import repo_file

    pidfile = tmp_path / "child.pid"
    step = ["sh", "-c", f"sleep 30 & echo $! > {pidfile}; sleep 30"]

    async def run() -> bool:
        started = time.monotonic()
        try:
            await repo_file.run_setup([step], str(tmp_path), budget=1.0)
            raise AssertionError("the budget did not stop the run")
        except repo_file.RepoFileRefused as exc:
            assert exc.code == "setup_timeout"
        assert time.monotonic() - started < 5.0, "the refusal waited on the step's child"
        child = int(pidfile.read_text().strip())
        for _ in range(60):
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                return False
            await asyncio.sleep(0.05)
        os.kill(child, 9)
        return True

    assert asyncio.run(run()) is False, "the step's child outlived the setup budget"


def test_a_setup_step_never_sees_the_servers_own_variables(tmp_path, monkeypatch):
    monkeypatch.setenv("CARNIVORE_HOOK_TOKEN", "sentinel-not-for-scripts")
    monkeypatch.setenv("PATH", os.environ.get("PATH", "/usr/bin:/bin"))
    out = asyncio.run(repo_file.run_setup([["/usr/bin/env"]], str(tmp_path)))
    assert "PATH=" in out
    assert "sentinel-not-for-scripts" not in out and "CARNIVORE_HOOK_TOKEN" not in out


@pytest.mark.parametrize("name", ["AuthKey_ABC.p8", "release.jks", "app.keystore", "kubeconfig", ".kube/kubeconfig.yaml",
                                  ".pgpass", ".htpasswd", "service-account.json", "serviceAccountKey.json"])
def test_more_credential_files_stay_unticked(name):
    assert repo_file.looks_secret(name)
    assert not repo_file.looks_secret("config/local.json")
