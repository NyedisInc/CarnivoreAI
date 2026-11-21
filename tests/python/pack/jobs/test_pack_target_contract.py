
from __future__ import annotations

import asyncio
import inspect
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.config import settings
from src.core.db import connect, db_path_for
from src.core.pack.jobs import policy as policy_mod, target as target_mod
from src.core.pack.jobs.engine import Engine
from src.core.pack.jobs.types import CollectAnswer, HostState, JobError, JobRequest, JobState, RunStatus, StartBody, StatusAnswer
from src.core.pack.machines.restrictions import Restrictions
from src.core.pack.transport import blobs
from tests.helpers.ssh_job_world import fingerprint, git, make_project, view_with

PROTOCOL = {n for n, _v in inspect.getmembers(target_mod.Target) if not n.startswith("_")} | {"install_id", "label"}


class MemoryTarget:

    install_id, label = "mem:one", "memory"

    def __init__(self, work: Path) -> None:
        self.work, self.calls, self.sent, self.body = work, [], "", None  # type: Any
        self.result_commit = ""

    async def admit(self, body: Any) -> None:
        self.calls.append("admit")

    async def send_bundle(self, path: str) -> str:
        self.calls.append("send_bundle")
        self.sent = str(self.work / "sent.bundle")
        Path(self.sent).write_bytes(Path(path).read_bytes())
        return "b-" + "1" * 30

    async def start(self, body: StartBody) -> str:
        self.calls.append("start")
        self.body = body
        return "preparing"

    async def status_full(self, job_id: str) -> StatusAnswer:
        self.calls.append("status_full")
        return StatusAnswer(state=HostState.EXITED, exit_code=0, output_tail="done in memory", output_bytes=14)

    async def status(self, job_id: str) -> RunStatus:
        self.calls.append("status")
        return RunStatus(HostState.EXITED, 0, None, "done in memory", 14)

    async def reply(self, body: Any) -> None:
        raise JobError("not_asking", "no worker here", 409)

    async def collect(self, job_id: str) -> CollectAnswer:
        self.calls.append("collect")
        repo, ref = self.work / "far", f"refs/carnivore/jobs/{self.body.job_id}/result"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        git(repo, "fetch", "-q", self.sent, f"+refs/heads/job-{self.body.job_id}:refs/heads/snap")
        git(repo, "checkout", "-q", "snap")
        (repo / "mem.txt").write_text("from memory\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "result")
        self.result_commit = git(repo, "rev-parse", "HEAD")
        git(repo, "update-ref", ref, self.result_commit)
        git(repo, "bundle", "create", str(self.work / "result.bundle"), ref, f"^{self.body.snapshot_commit}")
        return CollectAnswer(result_commit=self.result_commit, blob_id=blobs.new_id(), changed=1)

    async def fetch_result(self, job_id: str, answer: CollectAnswer, state_dir: Path) -> str:
        self.calls.append("fetch_result")
        return str(self.work / "result.bundle")

    async def stop(self, job_id: str, keep_files: bool) -> None:
        self.calls.append("stop")

    async def release(self, job_id: str) -> None:
        self.calls.append("release")

    async def install(self, job_id: str, project_uid: str, tools: List[str]) -> List[Dict[str, Any]]:
        raise JobError("no_brew", "nothing installs here", 409)

    async def install_status(self, install_id: str) -> Dict[str, Any]:
        raise JobError("no_brew", "nothing installs here", 409)


class Strict:

    def __init__(self, inner: MemoryTarget) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        if name not in PROTOCOL:
            raise AssertionError(f"the engine reached for {name!r}, which the Target protocol does not name")
        return getattr(self._inner, name)


def test_the_fake_has_every_protocol_member_and_the_protocol_names_fetch_result() -> None:
    assert "fetch_result" in PROTOCOL
    assert PROTOCOL - {"install_id", "label"} <= {n for n, _v in inspect.getmembers(MemoryTarget)}, "the fake implements the whole protocol"


def test_a_whole_job_runs_through_the_protocol_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state, jobs, root, uid = make_project(tmp_path)
    monkeypatch.setattr(type(settings), "get_state_dir", lambda _self: state, raising=True)
    work = tmp_path / "memory computer"
    work.mkdir()
    memory = MemoryTarget(work)
    before = fingerprint(root)

    async def no_carry(_root: str, _uid: str, _peer: str) -> None:
        pass

    async def fast(seconds: float) -> None:
        await asyncio.sleep(0.01)

    async def flow() -> Any:
        engine = Engine(state_dir=state, jobs_root=jobs, install_id="iid-a", open_db=lambda: connect(db_path_for(state), create=False),
                        view_for=lambda r, u: view_with("mem:one", "memory"), target_for=lambda iid: Strict(memory), sleep=fast,  # type: ignore[arg-type]
                        restrictions=lambda: Restrictions(may_host_agents=False), carry_commits=no_carry)
        policy_mod.set_auto(engine.store, uid, True)
        waiting = await engine.propose(JobRequest(command="touch mem.txt", folder=str(root), kind="suite", caller_session="ses_t", time_cap_s=60))
        assert waiting.state == JobState.WAITING_APPROVAL and waiting.peer_install_id == "mem:one", waiting
        await engine.proceed(waiting.id)
        end = time.monotonic() + 60
        while time.monotonic() < end:
            rec = engine.store.get_job(waiting.id)
            if rec.state in (JobState.DONE, JobState.FAILED, JobState.HERE):
                await asyncio.sleep(0.1)
                return rec
            await asyncio.sleep(0.05)
        raise AssertionError("the job did not end")

    done = asyncio.run(flow())
    assert done.state == JobState.DONE and done.result_commit == memory.result_commit, done
    assert (root / "mem.txt").read_text() == "from memory\n"
    assert memory.calls[:3] == ["admit", "send_bundle", "start"] and {"collect", "fetch_result", "release"} <= set(memory.calls), memory.calls
    assert fingerprint(root) == before
