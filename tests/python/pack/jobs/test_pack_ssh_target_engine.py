
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import re
import struct
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, List, Optional

import pytest

from src.config import settings
from src.core.db import connect, db_path_for
from src.core.hosts.ssh_exec import ExecResult
from src.core.pack.jobs import paths, policy as policy_mod
from src.core.pack.jobs.engine import Engine
from src.core.pack.jobs.ssh import conn as conn_mod, target as ssh_target
from src.core.pack.jobs.ssh.conn import SshConn, pin_key
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.target import SSH_PREFIX
from src.core.pack.jobs.types import AdmitBody, AgentSpec, JobError, JobRequest, JobState, ReplyBody, StartBody
from src.core.pack.machines.restrictions import Restrictions
from tests.helpers import fake_far
from tests.helpers.fake_ssh import FakeSshHost, fake_ssh_host_fixture
from tests.helpers.ssh_job_world import fingerprint, git, make_project, view_with

KEY = "fakehost000001"
TID = SSH_PREFIX + KEY
MARKER = "cvj-marker-7c1e9d52a0b34f68"


def make_key() -> "tuple[str, str]":
    blob = struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", 32) + hashlib.sha256(b"k").digest()
    return "ssh-ed25519 " + base64.b64encode(blob).decode(), "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")


class SpyConn(SshConn):

    def __init__(self, *args: Any, **kw: Any) -> None:
        super().__init__(*args, **kw)
        self.sent: List[bytes] = []
        self.dead = False
        self.before_download: Optional[Callable[[], None]] = None

    async def call(self, script: bytes, timeout: float) -> ExecResult:
        self.sent.append(script)
        if self.dead:
            raise JobError("unreachable", "no answer", 502)
        return await super().call(script, timeout)

    async def download(self, far_root: str, job_id: str, size: int, sha256: str, dest: Path) -> None:
        if self.before_download:
            self.before_download()
        await super().download(far_root, job_id, size, sha256, dest)

    def verbs(self) -> List[str]:
        return [m.group(1).decode() for s in self.sent if (m := re.search(rb"CVJ_VERB='([a-z]+)'", s))]


class World:

    def __init__(self, tmp: Path, fake: FakeSshHost, monkeypatch: pytest.MonkeyPatch, clock: Callable[[], float] = time.time) -> None:
        self.tmp, self.fake = tmp, fake
        self.state, self.jobs, self.root, self.uid = make_project(tmp)
        monkeypatch.setattr(type(settings), "get_state_dir", lambda _self: self.state, raising=True)
        self.home = fake.root / "home"
        fake.set("path", fake_far.far_path(self.home))
        public, fp = make_key()
        pin_key(KEY, fp, public, self.state)
        host = SimpleNamespace(key=KEY, ssh_target="alex@fakehost", ssh_port=2222, login_shell="/bin/sh")
        self.conn = SpyConn(host, self.state, pinned_fp=fp, ssh_binary=fake.ssh_binary, control_dir=fake.control_dir, connect_timeout=5.0,
                            check_interval=0.5, delay=lambda attempt: 0.05)
        self.store = JobStore(self.state)
        self.store.ssh_target_put(KEY, takes_work=1, pinned_fp=fp)
        self.target = ssh_target.SshTarget(KEY, conn=self.conn, store=self.store, clock=clock, label="farbox")

    def engine(self, *, sleep: Optional[Callable[[float], Any]] = None, clock: Callable[[], float] = time.time, lost_after_s: float = 90.0) -> Engine:

        async def fast(seconds: float) -> None:
            await asyncio.sleep(min(seconds, 0.1))

        engine = Engine(state_dir=self.state, jobs_root=self.jobs, install_id="iid-a", open_db=lambda: connect(db_path_for(self.state), create=False),
                        view_for=lambda root, uid: view_with(TID, "farbox"), target_for=lambda iid: self.target, sleep=sleep or fast, clock=clock,
                        lost_after_s=lost_after_s, restrictions=lambda: Restrictions(may_host_agents=False, may_receive_projects=False))
        policy_mod.set_auto(engine.store, self.uid, True)
        return engine

    def request(self, command: str, **kw: Any) -> JobRequest:
        return JobRequest(command=command, folder=str(self.root), kind="suite", caller_session="ses_test", time_cap_s=kw.pop("time_cap_s", 60), **kw)

    def metas(self) -> List[str]:
        meta = self.home / ".carnivore-ssh-jobs" / "meta"
        return sorted(p.name for p in meta.iterdir()) if meta.is_dir() else []

    async def until(self, engine: Engine, job_id: str, states: "set[JobState]", seconds: float = 90.0) -> Any:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            rec = engine.store.get_job(job_id)
            if rec is not None and rec.state in states:
                return rec
            await asyncio.sleep(0.05)
        raise AssertionError(f"job still {engine.store.get_job(job_id).state} after {seconds}s")

    async def released(self, seconds: float = 20.0) -> None:
        end = time.monotonic() + seconds
        while self.metas() and time.monotonic() < end:
            await asyncio.sleep(0.1)
        assert self.metas() == [], "the far folder is released after the collect"

    async def close(self) -> None:
        await self.conn.close()
        fake_far.kill_leftovers(self.home)


@pytest.fixture()
def build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    gen = fake_ssh_host_fixture()
    fake = next(gen)
    made: List[World] = []

    def factory(**kw: Any) -> World:
        made.append(World(tmp_path, fake, monkeypatch, **kw))
        return made[-1]

    yield factory
    next(gen, None)


@pytest.mark.asyncio
async def test_a_job_runs_on_the_ssh_computer_and_lands_and_nothing_of_this_process_travels(build, monkeypatch) -> None:
    monkeypatch.setenv("CVJ_MARKER_SECRET", MARKER)
    monkeypatch.setenv("SHELL", "/bin/" + MARKER)
    w = build()
    (w.root / "f.txt").write_text("changed\n")
    (w.root / "u.txt").write_text("untracked\n")
    before = fingerprint(w.root)
    engine = w.engine()
    try:
        waiting = await engine.propose(w.request("test -f u.txt && grep -q changed f.txt && echo hi && echo ok > out.txt; exit 3", env={"WHO": "me"}))
        assert waiting.state == JobState.WAITING_APPROVAL and waiting.peer_install_id == TID, waiting
        await engine.proceed(waiting.id)
        done = await w.until(engine, waiting.id, {JobState.DONE, JobState.FAILED, JobState.HERE})
        assert done.state == JobState.DONE and done.exit_code == 3 and "hi" in (done.output_tail or ""), done
        assert (w.root / "out.txt").read_text() == "ok\n" and "out.txt" in done.land_json
        assert fingerprint(w.root) == before
        head = git(w.root, "rev-parse", "HEAD")
        assert w.store.ssh_seed_get(w.uid, KEY)["head"] == head and w.store.base_get(w.uid, TID) == head
        await w.released()
        verbs = w.conn.verbs()
        assert verbs[0] == "hello" and {"claim", "seal", "start", "status", "collect", "release"} <= set(verbs), verbs
        everything = b"".join(w.conn.sent) + b"".join(json_argv.encode() for json_argv in (str(c["argv"]) for c in w.fake.calls()))
        assert b"echo hi" in everything and b"WHO" in everything, "the search covers what was really sent"
        assert MARKER.encode() not in everything
    finally:
        await w.close()


@pytest.mark.asyncio
async def test_a_stale_base_walks_the_bundle_ladder(build) -> None:
    w = build()
    engine = w.engine()
    try:
        w.store.base_set(w.uid, TID, git(w.root, "rev-parse", "HEAD"))
        (w.root / "g.txt").write_text("x\n")
        waiting = await engine.propose(w.request("echo ok > o2.txt"))
        await engine.proceed(waiting.id)
        done = await w.until(engine, waiting.id, {JobState.DONE, JobState.FAILED, JobState.HERE})
        assert done.state == JobState.DONE, done
        assert w.conn.verbs().count("start") == 2, w.conn.verbs()
        assert (w.root / "o2.txt").read_text() == "ok\n"
    finally:
        await w.close()


@pytest.mark.asyncio
async def test_the_caller_stops_a_job_the_far_side_never_ends(build) -> None:
    now = [1_000_000.0]
    w = build(clock=lambda: now[0])

    async def tick(_s: float) -> None:
        now[0] += 1000.0
        await asyncio.sleep(0.05)

    engine = w.engine(sleep=tick, clock=lambda: now[0])
    try:
        waiting = await engine.propose(w.request("sleep 120", time_cap_s=3600))
        await engine.proceed(waiting.id)
        done = await w.until(engine, waiting.id, {JobState.DONE, JobState.FAILED, JobState.LOST, JobState.HERE})
        assert done.state == JobState.FAILED and done.error_detail == ssh_target.NOT_IN_TIME, done
        assert {"stop", "release"} <= set(w.conn.verbs())
        await w.released()
    finally:
        await w.close()


@pytest.mark.asyncio
async def test_a_far_side_that_stops_answering_reads_lost(build) -> None:
    now = [1_000_000.0]
    w = build(clock=lambda: now[0])

    async def tick(_s: float) -> None:
        now[0] += 50.0
        await asyncio.sleep(0.05)

    engine = w.engine(sleep=tick, clock=lambda: now[0], lost_after_s=90.0)
    try:
        waiting = await engine.propose(w.request("sleep 30"))
        await engine.proceed(waiting.id)
        await w.until(engine, waiting.id, {JobState.RUNNING})
        w.conn.dead = True
        done = await w.until(engine, waiting.id, {JobState.LOST, JobState.DONE, JobState.FAILED})
        assert done.state == JobState.LOST and done.error_code == "lost", done
    finally:
        w.conn.dead = False
        await w.close()


@pytest.mark.asyncio
async def test_a_download_that_stalls_ends_inside_its_bound_and_lands_nothing(build, monkeypatch) -> None:
    monkeypatch.setattr(conn_mod, "TRANSFER_BASE_SECONDS", 1.0)
    w = build()
    release = threading.Event()

    def stall() -> None:
        bundle = w.home / ".carnivore-ssh-jobs" / "out" / f"{waiting.id}.bundle"
        bundle.unlink()
        os.mkfifo(bundle)

        def writer() -> None:
            end, fd = time.time() + 10, None
            while fd is None and time.time() < end:
                try:
                    fd = os.open(bundle, os.O_WRONLY | os.O_NONBLOCK)
                except OSError:
                    time.sleep(0.05)
            if fd is not None:
                os.write(fd, b"abc")
                release.wait(10)
                os.close(fd)

        threading.Thread(target=writer, daemon=True).start()

    engine = w.engine()
    try:
        waiting = await engine.propose(w.request("echo ok > o3.txt"))
        w.conn.before_download = stall
        await engine.proceed(waiting.id)
        began = time.monotonic()
        done = await w.until(engine, waiting.id, {JobState.DONE, JobState.FAILED, JobState.LOST, JobState.HERE}, 30)
        assert done.state == JobState.FAILED and done.error_code == "far_transfer_failed", done
        assert time.monotonic() - began < 20
        assert not list((w.state / "pack" / "inbox").glob("*")), "no temporary file is left"
        assert not (w.root / "o3.txt").exists(), "nothing landed"
    finally:
        release.set()
        await w.close()


@pytest.mark.asyncio
async def test_an_agent_body_and_everything_beyond_a_command_job_is_refused(build) -> None:
    w = build()
    job = paths.new_job_id()
    common = dict(job_id=job, project_uid=w.uid, snapshot_commit="a" * 40, snapshot_blob_id="b-" + "0" * 30, kind="suite", caller_roots=["/x/p"])
    try:
        with pytest.raises(JobError) as agent:
            await w.target.start(StartBody(agent=AgentSpec(task="t", family="claude", permission_mode="default"), **common))
        with pytest.raises(JobError) as reply:
            await w.target.reply(ReplyBody(job_id=job, text="y"))
        with pytest.raises(JobError) as install:
            await w.target.install(job, w.uid, ["ffmpeg"])
        with pytest.raises(JobError) as admit:
            await w.target.admit(AdmitBody(job_id=job, project_uid=w.uid, kind="suite", agent_family="claude"))
        assert {agent.value.code, reply.value.code, install.value.code, admit.value.code} == {"agent_jobs_not_here"}
        assert w.target.capabilities == ("pack.jobs",)
        with pytest.raises(JobError) as nul:
            await w.target.start(StartBody(command="echo a\0b", **common))
        assert nul.value.code == "bad_request" and w.conn.sent == [] and w.fake.calls() == [], "nothing was sent"
        w.store.ssh_target_put(KEY, takes_work=0)
        with pytest.raises(JobError) as off:
            await w.target.admit(AdmitBody(job_id=job, project_uid=w.uid, kind="suite"))
        assert off.value.code == "pack_restricted" and w.conn.sent == []
    finally:
        await w.close()


class Hostile:

    def __init__(self, answer: Callable[[str], bytes]) -> None:
        self.answer, self.sent = answer, []

    async def call(self, script: bytes, timeout: float) -> ExecResult:
        nonce = re.search(rb"CVJ_NONCE='([0-9a-f]{32})'", script).group(1).decode()
        verb = re.search(rb"CVJ_VERB='([a-z]+)'", script).group(1).decode()
        self.sent.append(verb)
        return ExecResult(0, self.answer(verb).replace(b"@@", f"CVJ{nonce} ".encode()), b"")


def hostile_target(tmp_path: Path, answer: Callable[[str], bytes]) -> ssh_target.SshTarget:
    store = JobStore(tmp_path)
    store.ssh_target_put(KEY, takes_work=1)
    return ssh_target.SshTarget(KEY, conn=Hostile(answer), store=store, label="evil")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_every_far_string_is_data(tmp_path: Path) -> None:
    long_reason = "r" * 600
    status = (b"@@state exited\n@@code 0\n@@reason " + long_reason.encode() + b"\n@@size 5\n@@out \x1b[31mred\x1b[0m\x07\xe2\x80\xae end\n@@end 0\n")
    target = hostile_target(tmp_path, lambda verb: status)
    got = await target.status_full(paths.new_job_id())
    assert got.output_tail == "red end" and len(got.detail) == 256 and not re.search("[\x00-\x08\x0b-\x1f\x7f-\x9f‮]", got.output_tail + got.detail)
    big = hostile_target(tmp_path, lambda verb: b"@@state running\n" + b"@@out " + b"x" * 200 + b"\n" * 400 + b"@@end 0\n" + b"x" * 70000)
    with pytest.raises(JobError) as huge:
        await big.status_full(paths.new_job_id())
    assert huge.value.code == "far_garbled"
    bad_root = hostile_target(tmp_path, lambda verb: b"@@root /a/../etc\n@@end 0\n")
    with pytest.raises(JobError) as root:
        await bad_root.admit(AdmitBody(job_id=paths.new_job_id(), project_uid="uid-test-0001", kind="suite"))
    assert root.value.code == "far_garbled"
    bad_slot = hostile_target(tmp_path, lambda verb: b"@@root /far/root\n@@end 0\n" if verb == "hello" else b"@@slot 1;rm\n@@end 0\n")
    common = dict(job_id=paths.new_job_id(), project_uid="uid-test-0001", snapshot_commit="a" * 40, snapshot_blob_id="b-" + "0" * 30, kind="suite",
                  caller_roots=["/x/p"], command="true")
    with pytest.raises(JobError) as slot:
        await bad_slot.start(StartBody(**common))
    assert slot.value.code == "far_garbled" and bad_slot._conn.sent == ["hello", "claim"], "nothing was started on a believed-bad slot"
    bad_commit = hostile_target(tmp_path, lambda verb: b"@@commit zz\n@@end 0\n")
    with pytest.raises(JobError) as commit:
        await bad_commit.collect(paths.new_job_id())
    assert commit.value.code == "far_garbled"


@pytest.mark.asyncio
async def test_a_far_refusal_never_borrows_a_code_this_computer_uses_itself(tmp_path: Path) -> None:
    for word, expected in (("no_free_slot", "no_free_slot"), ("unreachable", "far_error"), ("host_key_changed", "far_error"), ("made_up", "far_error")):
        evil = hostile_target(tmp_path, lambda verb, w=word: f"@@error {w} nope\n@@end 1\n".encode())
        with pytest.raises(JobError) as got:
            await evil.admit(AdmitBody(job_id=paths.new_job_id(), project_uid="uid-test-0001", kind="suite"))
        assert got.value.code == expected, word


def test_an_owner_setup_override_rides_on_stdin_and_never_on_the_far_command_line() -> None:
    from src.core.pack.jobs import recipe

    steps = recipe.plan("/far/slot1", [], {}, ["NPM_TOKEN=abc npm ci"], shell="/bin/bash")
    script = ssh_target.steps_script(steps)
    assert "-c" not in script.split("<<")[0] and script.startswith("cd /far/slot1 || exit 1\n/bin/bash -l -s <<'OVERRIDE_")
    assert "\nNPM_TOKEN=abc npm ci\nOVERRIDE_" in script
