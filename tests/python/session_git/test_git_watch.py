
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.session_git_routes import router
from src.core.resource_push.topics import GIT_STATUS, RESOURCE_TOPICS, family_of
from src.core.session_git.repo_cache import RepoCache
from src.core.session_git.watch import KEEPALIVE_SECONDS, LEASE_SECONDS, TICK_SECONDS, GitStatusWatch
from src.models.session_git import GitCounts, SessionGitStatus


class Rig:

    def __init__(self, tmp_path: Path) -> None:
        self.repo = tmp_path / "repo"
        (self.repo / ".git").mkdir(parents=True)
        (self.repo / "src").mkdir()
        self.head, self.index = self.repo / ".git" / "HEAD", self.repo / ".git" / "index"
        self.head.write_text("ref: refs/heads/main\n")
        self.index.write_text("x")
        self.now = 1000.0
        self.spawns = 0
        self.dirty_files = 0
        self.unknown = False
        self.named: List[str] = []
        self._go = asyncio.Semaphore(0)
        self.cache = RepoCache(self._read, clock=lambda: self.now)
        self.watch = GitStatusWatch(self.cache, notify=self.named.append, sleep=self._sleep, clock=lambda: self.now)

    def _read(self, directory: Path) -> SessionGitStatus:
        self.spawns += 1
        if self.unknown:
            return SessionGitStatus(state="unknown", read_at=self.now)
        return SessionGitStatus(state="ok", branch="main", counts=GitCounts(unstaged=self.dirty_files), read_at=self.now)

    async def _sleep(self, seconds: float) -> None:
        await self._go.acquire()

    async def step(self, seconds: float = TICK_SECONDS) -> None:
        self.now += seconds
        self._go.release()
        await asyncio.sleep(0.05)

    def touch_index(self) -> None:
        st = self.index.stat()
        os.utime(self.index, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))


@pytest.mark.asyncio
async def test_idle_spawns_nothing_and_two_sessions_in_one_repo_share_one_read(tmp_path) -> None:
    rig = Rig(tmp_path)
    await asyncio.sleep(0.02)
    assert rig.spawns == 0 and not rig.watch.running
    a = await rig.watch.read("ses_a", rig.repo)
    b = await rig.watch.read("ses_b", rig.repo / "src")
    assert rig.spawns == 1 and a.state == b.state == "ok" and rig.watch.running
    await rig.step()
    await rig.step()
    assert rig.spawns == 1 and rig.named == []
    await rig.watch.stop()


@pytest.mark.asyncio
async def test_notifies_only_when_the_result_changes_and_respects_the_floor(tmp_path) -> None:
    rig = Rig(tmp_path)
    await rig.watch.read("ses_a", rig.repo)
    await rig.watch.read("ses_b", rig.repo / "src")
    rig.touch_index()
    await rig.step(11)
    assert rig.spawns == 2 and rig.named == []
    rig.dirty_files = 3
    rig.touch_index()
    await rig.step(5)
    assert rig.spawns == 2 and rig.named == []
    await rig.watch.read("ses_a", rig.repo)
    await rig.step(6)
    assert rig.spawns == 3
    assert sorted(rig.named) == ["git_status:ses_a", "git_status:ses_b"]
    assert family_of(rig.named[0]) == GIT_STATUS and GIT_STATUS in RESOURCE_TOPICS
    await rig.watch.stop()


@pytest.mark.asyncio
async def test_turn_end_forces_one_reread_and_unknown_is_retried(tmp_path) -> None:
    rig = Rig(tmp_path)
    await rig.watch.read("ses_a", rig.repo)
    rig.dirty_files = 2
    rig.watch.on_status("ses_a", "working")
    await rig.step(11)
    assert rig.spawns == 1
    rig.watch.on_status("ses_a", "idle")
    await rig.step(5)
    assert rig.spawns == 2 and rig.named == ["git_status:ses_a"]
    rig.unknown = True
    rig.touch_index()
    await rig.watch.read("ses_a", rig.repo)
    await rig.step(11)
    spawns = rig.spawns
    await rig.step(11)
    assert rig.spawns == spawns + 1
    assert rig.named[-1] == "git_status:ses_a"
    assert (await rig.watch.read("ses_a", rig.repo)).state == "unknown"
    await rig.watch.stop()


@pytest.mark.asyncio
async def test_keepalive_renews_and_a_lapsed_lease_ends_the_task(tmp_path) -> None:
    rig = Rig(tmp_path)
    await rig.watch.read("ses_a", rig.repo)
    for _ in range(int(KEEPALIVE_SECONDS // TICK_SECONDS)):
        await rig.step()
    assert rig.named == ["git_status:ses_a"] and rig.spawns == 1
    for _ in range(int(LEASE_SECONDS // TICK_SECONDS) + 2):
        await rig.step()
    assert not rig.watch.running
    assert rig.cache._entries == {}


def test_a_paired_computer_session_answers_remote_and_reads_nothing(tmp_path) -> None:
    class Manager:
        _registry = None

        async def get_session_info(self, session_id):
            raise AssertionError("a remote session must not be looked up locally")

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.session_manager = Manager()
    with TestClient(app) as http:
        body = http.get("/api/v1/sessions/remote:peer-abc:carnivore_x/git-status").json()
    assert body["state"] == "remote" and not hasattr(app.state, "git_status_watch")


@pytest.mark.asyncio
async def test_tick_survives_an_unexpected_exception(tmp_path) -> None:
    rig = Rig(tmp_path)
    await rig.watch.read("ses_a", rig.repo)
    real_get, calls = rig.cache.get, {"n": 0}

    async def flaky(directory, *, force=False):
        calls["n"] += 1
        if calls["n"] == 1:
            raise KeyError("boom")
        return await real_get(directory, force=force)

    rig.cache.get = flaky
    await rig.step()
    assert rig.watch.running
    await rig.step(KEEPALIVE_SECONDS)
    assert calls["n"] >= 2 and rig.watch.running and "ses_a" in rig.watch._s.viewers
    await rig.watch.stop()


def test_the_answer_carries_the_stored_folder_resolved_and_leaves_the_shared_read_alone(tmp_path) -> None:
    real = tmp_path / "repo"
    (real / "web").mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    shared = SessionGitStatus(state="ok", repo_root=os.path.realpath(real))

    class Watch:
        async def read(self, session_id, directory):
            assert Path(directory) == alias / "web"
            return shared

    class Info:
        tmux_session = None

        class session:  # noqa: N801
            working_dir = str(alias / "web")

    class Manager:
        _registry = None

        async def get_session_info(self, session_id):
            return Info()

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.session_manager = Manager()
    app.state.git_status_watch = Watch()
    with TestClient(app) as http:
        body = http.get("/api/v1/sessions/ses_1/git-status").json()
    assert body["working_dir_real"] == os.path.realpath(real / "web")
    assert body["working_dir_real"].startswith(body["repo_root"] + "/")
    assert shared.working_dir_real is None
