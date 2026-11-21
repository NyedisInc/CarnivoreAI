
from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path

import pytest

from src.core.pack.jobs import folders, recipe
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import DepDir, JobError

UID = "uid12345678"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t.invalid", *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def env(tmp_path: Path):
    repo = tmp_path / "my repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / ".gitignore").write_text("node_modules/\n*.report\n")
    (repo / "a.txt").write_text("one\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "c1")
    return JobStore(tmp_path / "state dir"), tmp_path / "jobs root", repo, _git(repo, "rev-parse", "HEAD")


def _acquire(env, n: int):
    store, root, repo, commit = env
    return folders.acquire(store, jobs_root=root, project_uid=UID, project_name="my repo", repo_root=str(repo), commit=commit,
                           job_id=f"job_{n:012x}")


def test_fresh_acquire_tree_and_repo_untouched(env):
    store, root, repo, commit = env
    head_before = _git(repo, "symbolic-ref", "-q", "HEAD")
    lease = _acquire(env, 1)
    assert lease.fresh and lease.slot == 1
    assert _git(Path(lease.path), "rev-parse", "HEAD^{tree}") == _git(repo, "rev-parse", f"{commit}^{{tree}}")
    assert _git(repo, "symbolic-ref", "-q", "HEAD") == head_before
    assert folders.busy_count(store, UID) == 1


def test_reuse_is_pristine_except_dependency_folders(env):
    store, root, repo, commit = env
    lease = _acquire(env, 1)
    slot = Path(lease.path)
    (slot / "node_modules").mkdir()
    (slot / "node_modules" / "m.js").write_text("x")
    (slot / "run.report").write_text("leftover")
    (slot / "a.txt").write_text("dirty\n")
    (slot / "new.txt").write_text("untracked")
    folders.release(store, path=lease.path, now=1000.0)
    again = _acquire(env, 2)
    assert again.path == lease.path and not again.fresh
    assert (slot / "a.txt").read_text() == "one\n"
    assert not (slot / "new.txt").exists() and not (slot / "run.report").exists()
    assert (slot / "node_modules" / "m.js").exists()


def test_fourth_acquire_refuses_and_failed_add_frees_slot(env):
    for n in (1, 2, 3):
        _acquire(env, n)
    with pytest.raises(JobError) as err:
        _acquire(env, 4)
    assert err.value.code == "no_free_slot"
    store, root, repo, _ = env
    with pytest.raises(JobError):
        folders.acquire(store, jobs_root=root, project_uid="other0000001", project_name="x", repo_root=str(repo), commit="f" * 40,
                        job_id="job_0000000000aa")
    assert store.slot_rows("other0000001") == []


def test_sweep_frees_kept_slot_and_removes_idle(env):
    store, root, repo, _ = env
    lease = _acquire(env, 1)
    folders.release(store, path=lease.path, keep_hours=1, now=1000.0)
    assert store.slot_rows(UID)[0]["keep_until"] == 1000.0 + 3600
    assert folders.sweep(store, now=1000.0 + 10) == []
    assert folders.sweep(store, now=1000.0 + 3601) == [lease.path]
    assert store.slot_rows(UID)[0]["keep_until"] is None
    assert folders.sweep(store, now=time.time() + 8 * 86400) == [lease.path]
    assert store.slot_rows(UID) == [] and not Path(lease.path).exists()
    assert "worktree" not in _git(repo, "worktree", "list").split("\n", 1)[-1]


def test_plan_orders_venv_before_pip_and_drops_unchanged_memo(tmp_path: Path):
    slot = str(tmp_path / "slot dir")
    npm = DepDir("web/node_modules", "npm", {"web/package-lock.json": "aa"})
    venv = DepDir(".venv", "venv", {"requirements.txt": "bb"}, "3.12")
    steps = recipe.plan(slot, [npm, venv], {}, None)
    argvs = [s.argv[:3] for s in steps]
    assert steps[0].argv == ["npm", "ci"] and steps[0].cwd == str(Path(slot, "web"))
    assert argvs[1] == ["python3.12", "-m", "venv"]
    assert argvs[2] == [".venv/bin/pip", "install", "-r"] and steps[2].argv[3] == "requirements.txt"
    assert steps[-1].argv[0] == "sh" and "playwright" in steps[-1].argv[2]
    current = {s.memo_key: s.memo_value for s in steps}
    assert recipe.plan(slot, [npm, venv], current, None) == []
    assert [s.argv[:2] for s in recipe.plan(slot, [npm, venv], {**current, ".venv": "stale"}, None)][0] == ["python3.12", "-m"]
    over = recipe.plan(slot, [npm], current, ["echo hi"])
    assert len(over) == 1 and over[0].argv[1:] == ["-l", "-c", "echo hi"] and over[0].cwd == slot


def test_run_stops_at_first_failure(tmp_path: Path):
    log_path = tmp_path / "logs" / "setup.log"
    cwd = str(tmp_path)
    steps = [recipe.Step(cwd, ["echo", "first"], "a", "1"), recipe.Step(cwd, ["false"], "b", "2"), recipe.Step(cwd, ["echo", "never"], "c", "3")]
    res = asyncio.run(recipe.run(steps, log_path))
    assert not res.ok and res.failed_step == 1 and res.memo == {"a": "1"}
    text = log_path.read_text()
    assert "first" in text and "never" not in text
    ok = asyncio.run(recipe.run([steps[0], steps[2]], log_path))
    assert ok.ok and ok.failed_step is None and ok.memo == {"a": "1", "c": "3"}
