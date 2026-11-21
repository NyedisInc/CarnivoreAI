
from __future__ import annotations

import asyncio
import functools
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from src.core.pack.jobs import folders, prewarm, recipe
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import DepDir, HostJob, HostState, JobError

UID = "uid12345abcd"


def arun(fn):
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


DEPS = [DepDir("web/node_modules", "npm", {"web/package-lock.json": "aa11"}, None)]


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=True).stdout.strip()


class FakeHost:

    def __init__(self, tmp: Path, root: Path) -> None:
        self.store, self.jobs_root, self.root = JobStore(tmp / "state"), tmp / "jobs", root
        self.admit_says: Optional[str] = None
        self.tasks: List["asyncio.Task[None]"] = []
        self.gate_error: Optional[JobError] = None

    def _gate_sync(self, caller: str, project_uid: str, **_: Any) -> Dict[str, Any]:
        if self.gate_error:
            raise self.gate_error
        return {"root": str(self.root), "air_gap": 0, "pack_state": "replica", "home_install_id": "peer-a"}

    def _admit(self, _work: Any) -> Optional[str]:
        return self.admit_says

    def _track(self, job_id: str, coro: Any) -> None:
        self.tasks.append(asyncio.ensure_future(coro))

    def _clock(self) -> float:
        return 1000.0


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "state").mkdir()
    repo = tmp_path / "proj"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "a.txt").write_text("x")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "one")
    host = FakeHost(tmp_path, repo)
    snap: Dict[str, Any] = {"pressure": {"pegged": False}, "battery": {"on_battery": False}}
    monkeypatch.setattr(prewarm.host_admit, "own_snapshot", lambda: snap)
    ran: List[int] = []

    async def fake_run(steps, log_path, **_: Any):
        ran.append(len(steps))
        return recipe.RecipeResult(True, None, 0.1, {s.memo_key: s.memo_value for s in steps})

    monkeypatch.setattr(prewarm.recipe, "run", fake_run)
    return SimpleNamespace(host=host, repo=repo, commit=git(repo, "rev-parse", "HEAD"), snap=snap, ran=ran)


def body(commit: str, **extra: Any) -> prewarm.PrewarmBody:
    return prewarm.PrewarmBody(project_uid=UID, commit=commit, dep_dirs=[{"path": "web/node_modules", "kind": "npm", "locks": {"web/package-lock.json": "aa11"}}],
                               **extra)


async def settle(host: FakeHost) -> None:
    await asyncio.gather(*host.tasks)


@arun
async def test_warms_one_slot_and_the_next_recipe_runs_zero_steps(world) -> None:
    host = world.host
    assert await prewarm.prewarm(host, "peer-a", body(world.commit)) == {"ok": True}
    assert host.store.host_get(prewarm.marker(UID)) is not None
    await settle(host)
    assert world.ran == [1] and host.store.host_get(prewarm.marker(UID)) is None
    (slot,) = host.store.slot_rows(UID)
    assert slot["job_id"] is None and recipe.plan(slot["path"], DEPS, slot["memo"], None) == []
    again = await prewarm.prewarm(host, "peer-a", body(world.commit))
    assert again["ok"] is False and "already set up" in again["reason"]


@arun
async def test_refusals_claim_nothing(world) -> None:
    host = world.host
    bad_commit = "f" * 40
    assert "does not have that commit" in (await prewarm.prewarm(host, "peer-a", body(bad_commit)))["reason"]
    world.snap["pressure"] = {"pegged": True, "why": "cpu"}
    assert "pegged" in (await prewarm.prewarm(host, "peer-a", body(world.commit)))["reason"]
    world.snap["pressure"] = {"pegged": False}
    world.snap["battery"] = {"on_battery": True}
    assert "battery" in (await prewarm.prewarm(host, "peer-a", body(world.commit)))["reason"]
    world.snap["battery"] = {"on_battery": False}
    host.admit_says = "this computer is busy"
    assert (await prewarm.prewarm(host, "peer-a", body(world.commit)))["reason"] == "this computer is busy"
    host.admit_says = None
    assert "setup commands" in (await prewarm.prewarm(host, "peer-a", body(world.commit, setup=["make"])))["reason"]
    host.store.host_put(HostJob(job_id="job_0123456789ab", caller_install="peer-a", project_uid=UID, state=HostState.RUNNING, snapshot_commit=world.commit))
    assert "running here" in (await prewarm.prewarm(host, "peer-a", body(world.commit)))["reason"]
    assert host.store.slot_rows(UID) == [] and not host.tasks


@arun
async def test_one_free_folder_refuses_and_a_gate_refusal_raises(world) -> None:
    host = world.host
    for n in (1, 2):
        folders.acquire(host.store, jobs_root=host.jobs_root, project_uid=UID, project_name="proj", repo_root=str(world.repo), commit=world.commit,
                        job_id=f"job_00000000000{n}")
    assert "fewer than two" in (await prewarm.prewarm(host, "peer-a", body(world.commit)))["reason"]
    host.gate_error = JobError("not_a_counterpart", "no", 403)
    with pytest.raises(JobError):
        await prewarm.prewarm(host, "peer-a", body(world.commit))


def test_body_is_strict_and_send_reports_an_unreachable_target() -> None:
    with pytest.raises(ValueError):
        prewarm.PrewarmBody(project_uid=UID, commit="abc")
    with pytest.raises(ValueError):
        prewarm.PrewarmBody(project_uid=UID, commit="a" * 40, extra=1)  # type: ignore[call-arg]

    async def dead(*_a: Any, **_k: Any):
        raise OSError("down")

    async def fine(method: str, path: str, **kw: Any):
        assert path == prewarm.PATH and kw["json"]["commit"] == "a" * 40
        return 200, {"ok": True}

    assert asyncio.run(prewarm.send(dead, UID, "a" * 40, DEPS, None))["ok"] is False
    assert asyncio.run(prewarm.send(fine, UID, "a" * 40, DEPS, None)) == {"ok": True}
