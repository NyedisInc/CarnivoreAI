
from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import time
from contextlib import ExitStack, closing
from pathlib import Path
from typing import Any, Dict, List

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import federation_pack_jobs_routes as jobs_routes  # noqa: E402
from src.api import federation_pack_transport_routes as transport_routes  # noqa: E402
from src.api import peer_auth  # noqa: E402
from src.config import settings  # noqa: E402
from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.federation import fed_key, grants  # noqa: E402
from src.core.pack.identity import replicas  # noqa: E402
from src.core.pack.jobs import paths, policy as policy_mod  # noqa: E402
from src.core.pack.jobs.engine import Engine  # noqa: E402
from src.core.pack.jobs.host import Host  # noqa: E402
from src.core.pack.jobs.place import PlaceView  # noqa: E402
from src.core.pack.jobs.store import JobStore  # noqa: E402
from src.core.pack.jobs.target import PeerTarget  # noqa: E402
from src.core.pack.jobs.types import CAP_JOBS, AdmitBody, JobError, JobRequest, JobState  # noqa: E402
from src.core.pack.machines.restrictions import Restrictions  # noqa: E402
from src.core.pack.placement import rule  # noqa: E402
from src.core.pack.transport import sync  # noqa: E402
from src.core.tmux_discovery import tmux_argv_prefix  # noqa: E402


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=True).stdout.strip()


def fingerprint(repo: Path) -> Dict[str, object]:
    files = {}
    for root, _d, names in os.walk(repo / ".git"):
        for n in names:
            p = Path(root) / n
            st = p.stat()
            rel = str(p.relative_to(repo))
            files[rel] = (st.st_size, 0 if rel.startswith(".git/objects/") else st.st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
    return {"files": files, "refs": git(repo, "for-each-ref")}


def snap(load1: float, *, may_host: bool = True) -> Dict[str, Any]:
    return {"load": {"cores": 10, "load_1": load1, "mem_total_gb": 32.0, "mem_available_gb": 28.0, "disk_free_gb": 200.0},
            "reserve": {"level": "away", "cpu_pct": 10, "mem_pct": 10}, "toolchain": {}, "restrictions": {"may_host_agents": may_host}}


class Machine:

    def __init__(self, tmp: Path, name: str, install_id: str) -> None:
        self.install_id = install_id
        self.state, self.jobs, self.root = tmp / f"{name} state", tmp / f"{name} jobs", tmp / f"{name} tra der"
        for folder in (self.state, self.jobs, self.root):
            folder.mkdir()
        assert ensure_db_migrated(self.state).status == "ok"
        git(self.root, "init", "-q", "-b", "main")
        self.restrictions = Restrictions()
        self.app = FastAPI()
        self.app.include_router(transport_routes.router, prefix="/api/v1")
        self.app.include_router(jobs_routes.router, prefix="/api/v1")
        self.client: TestClient

    def conn(self):
        return connect(db_path_for(self.state), create=False)


@pytest.fixture()
def world(monkeypatch, tmp_path, tmux_test_socket):
    a, b = Machine(tmp_path, "a", "iid-a"), Machine(tmp_path, "b", "iid-b")
    machines = {"iid-a": a, "iid-b": b}
    current = [a]
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: current[0].state, raising=True)

    async def no_copy_sync(*_args: Any, **_kw: Any) -> None:
        pass

    monkeypatch.setattr(transport_routes.pack_copy_sync, "after_apply", no_copy_sync)

    def link(sender: Machine, receiver: Machine):
        with closing(receiver.conn()) as conn:
            if not any(g.peer_install_id == sender.install_id for g in grants.list_grants(conn)):
                key = fed_key.public_key_b64(fed_key.DeviceKey.from_seed(bytes([7]) * 32))
                grants.create_grant(conn, peer_install_id=sender.install_id, public_key=key, label=sender.install_id, scopes=("replica",))
            grant = next(g for g in grants.list_grants(conn) if g.peer_install_id == sender.install_id)
        principal = peer_auth.Principal("peer", grant)
        for dep in (transport_routes._require_replica, jobs_routes._require_replica):
            receiver.app.dependency_overrides[dep] = lambda p=principal: p

        async def request(method: str, path: str, *, content: Any = None, headers: Any = None, json: Any = None):
            before, current[0] = current[0], receiver
            try:
                reply = receiver.client.request(method, "/api/v1" + path, content=content, headers=headers, json=json)
            finally:
                current[0] = before
            return reply.status_code, reply.json()

        return request

    host = Host(state_dir=b.state, jobs_root=b.jobs, install_id="iid-b", socket=tmux_test_socket, open_db=b.conn,
                restrictions=lambda: b.restrictions, live_agents=lambda: 0, admit=lambda w: None, request_for=lambda iid: link(b, machines[iid]))
    b.app.state.pack_jobs_host = host
    (a.root / "f.txt").write_text("one\n")
    git(a.root, "add", "f.txt")
    git(a.root, "commit", "-q", "-m", "first")
    with ExitStack() as stack:
        a.client = stack.enter_context(TestClient(a.app))
        b.client = stack.enter_context(TestClient(b.app))
        with closing(a.conn()) as conn:
            conn.execute("INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at) VALUES (?, ?, 'tra der', 'user', 't', 't')",
                         (str(a.root), str(a.root)))
            conn.commit()
            uid = conn.execute("SELECT uid FROM projects").fetchone()[0]
            replicas.record_replica(conn, uid, "iid-b", str(b.root), "carried")
        with closing(b.conn()) as conn:
            conn.execute("INSERT INTO projects (root, raw_path, display_name, source, uid, pack_state, home_install_id, created_at, updated_at) "
                         "VALUES (?, ?, 'tra der', 'user', ?, 'replica', 'iid-a', 't', 't')", (str(b.root), str(b.root), uid))
            conn.commit()
        carried = asyncio.run(sync.carry_bundle(repo=str(a.root), project_uid=uid, peer_install_id="iid-b", request=link(a, b), open_db=a.conn,
                                                outbox=str(a.state / "pack" / "outbox"), air_gap=True))
        assert carried["sent"], carried
        w = type("World", (), {})()
        w.a, w.b, w.uid, w.host, w.tmp, w.carries = a, b, uid, host, tmp_path, []

        async def fast(seconds: float) -> None:
            await asyncio.sleep(min(seconds, 0.1))

        async def counting_carry(root: str, project_uid: str, peer: str) -> None:
            w.carries.append(peer)
            await sync.carry_bundle(repo=root, project_uid=project_uid, peer_install_id=peer, request=link(a, b), open_db=a.conn,
                                    outbox=str(a.state / "pack" / "outbox"), air_gap=True)

        def make_engine(*, b_snapshot: Dict[str, Any] = None, on: bool = True) -> Engine:
            me = rule.MachineInput("iid-a", "a", snap(9.5, may_host=False), True, True, True, True, 0)
            other = rule.MachineInput("iid-b", "b", b_snapshot or snap(1.0), True, False, False, True, None)
            engine = Engine(state_dir=a.state, jobs_root=a.jobs, install_id="iid-a", open_db=a.conn,
                            view_for=lambda root, puid: PlaceView(me, [other], {"iid-b": [CAP_JOBS]}, "iid-a", None),
                            target_for=lambda iid: PeerTarget(iid, "b", link(a, machines[iid])), sleep=fast,
                            restrictions=lambda: a.restrictions, carry_commits=counting_carry)
            if on:
                policy_mod.set_auto(engine.store, uid, True)
            return engine

        w.engine, w.link = make_engine, link
        yield w
    for rec in JobStore(a.state).list_jobs(limit=500):
        subprocess.run(tmux_argv_prefix(tmux_test_socket) + ["kill-session", "-t", "=" + paths.session_name(rec.id)], capture_output=True, check=False)


def request(w, command: str, folder: Path = None, **kw: Any) -> JobRequest:
    return JobRequest(command=command, folder=str(folder or w.a.root), kind="suite", caller_session="ses_test", time_cap_s=60, **kw)


def test_happy_path_leaves_the_callers_git_dir_untouched(world) -> None:
    w = world
    root = w.a.root
    (root / "s.txt").write_text("staged\n")
    git(root, "add", "s.txt")
    (root / "f.txt").write_text("changed\n")
    (root / "u.txt").write_text("untracked\n")
    before = fingerprint(root)
    engine = w.engine()

    async def flow():
        waiting = await engine.propose(request(w, "sleep 1; test -f u.txt && test -f s.txt && grep -q changed f.txt && echo hi && echo ok > out.txt; exit 3"))
        assert waiting.state == JobState.WAITING_APPROVAL and waiting.peer_install_id == "iid-b", waiting
        began = time.monotonic()
        await engine.proceed(waiting.id)
        return waiting, await engine.wait(waiting.id, 90), time.monotonic() - began

    waiting, done, took = asyncio.run(flow())
    assert done.state == JobState.DONE and done.exit_code == 3 and "hi" in (done.output_tail or ""), done
    slot = w.host.store.host_get(waiting.id).slot_path
    assert git(Path(slot), "rev-parse", "HEAD^{tree}") == waiting.snapshot_tree
    assert (root / "out.txt").read_text() == "ok\n"
    assert "out.txt" in done.land_json
    assert fingerprint(root) == before
    assert w.carries == [], "the peer held the history, so no commit carry"
    print(f"WARM OVERHEAD proceed to done {took:.2f}s, command 1s, overhead {took - 1:.2f}s")


def test_mark_off_runs_here_and_makes_no_side_repository(world) -> None:
    w = world
    engine = w.engine(on=False)
    rec = asyncio.run(engine.propose(request(w, "echo hi")))
    assert rec.state == JobState.HERE and "set to this computer only" in rec.reason
    assert not (w.a.jobs / "repos").exists()


def test_may_host_agents_off_is_honoured_on_both_sides(world) -> None:
    w = world
    rec = asyncio.run(w.engine(b_snapshot=snap(1.0, may_host=False)).propose(request(w, "echo hi")))
    assert rec.state == JobState.HERE and "may_host_agents" in rec.reason, rec.reason
    w.b.restrictions = Restrictions(may_host_agents=False)
    peer = PeerTarget("iid-b", "b", w.link(w.a, w.b))
    with pytest.raises(JobError) as refused:
        asyncio.run(peer.admit(AdmitBody(job_id=paths.new_job_id(), project_uid=w.uid, kind="suite")))
    assert refused.value.code == "pack_restricted"


def test_a_clash_keeps_the_callers_file_and_parks_the_result(world) -> None:
    w = world
    engine = w.engine()

    async def flow():
        waiting = await engine.propose(request(w, "echo theirs > out.txt"))
        (w.a.root / "out.txt").write_text("mine\n")
        await engine.proceed(waiting.id)
        return await engine.wait(waiting.id, 90)

    done = asyncio.run(flow())
    assert done.state == JobState.DONE, done
    assert '"clashes": ["out.txt"]' in done.land_json
    assert (w.a.root / "out.txt").read_text() == "mine\n"
    assert git(w.a.root, "rev-parse", f"refs/carnivore/jobs/{done.id}") == done.result_commit


def test_a_second_identical_propose_returns_the_same_job(world) -> None:
    w = world
    engine = w.engine()

    async def flow():
        first = await engine.propose(request(w, "sleep 2; echo hi"))
        again = await engine.propose(request(w, "sleep 2; echo hi"))
        await engine.proceed(first.id)
        later = await engine.propose(request(w, "sleep 2; echo hi"))
        return first, again, later, await engine.wait(first.id, 90)

    first, again, later, done = asyncio.run(flow())
    assert first.id == again.id == later.id
    assert again.state == JobState.WAITING_APPROVAL and later.state == JobState.MIRRORING
    assert done.state == JobState.DONE and len(JobStore(w.a.state).list_jobs()) == 1


def test_the_commit_carry_runs_once_when_the_peer_has_no_tips(world) -> None:
    w = world
    with closing(w.a.conn()) as conn:
        conn.execute("DELETE FROM pack_bundle_tips")
        conn.commit()
    engine = w.engine()

    async def flow():
        rec = await engine.submit(request(w, "echo hi"))
        return await engine.wait(rec.id, 90)

    done = asyncio.run(flow())
    assert done.state == JobState.DONE and "hi" in (done.output_tail or ""), done
    assert w.carries == ["iid-b"]


def test_a_linked_worktree_resolves_to_its_project_and_runs(world) -> None:
    w = world
    tree = w.tmp / "a tra der wt"
    git(w.a.root, "worktree", "add", "-q", "-b", "wt", str(tree))
    (tree / "w.txt").write_text("from the worktree\n")
    engine = w.engine()

    async def flow():
        rec = await engine.submit(request(w, "cat w.txt > copy.txt", folder=tree))
        assert rec.project_uid == w.uid and rec.state == JobState.MIRRORING, rec
        return await engine.wait(rec.id, 90)

    done = asyncio.run(flow())
    assert done.state == JobState.DONE and done.exit_code == 0, done
    assert (tree / "copy.txt").read_text() == "from the worktree\n"
    assert not (w.a.root / "copy.txt").exists()
