
from __future__ import annotations

import asyncio
import os
import subprocess
import time
import uuid
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
from src.core.pack.jobs import bundle_io, folders, paths, runner  # noqa: E402
from src.core.pack.jobs.host import Host  # noqa: E402
from src.core.pack.jobs.store import JobStore  # noqa: E402
from src.core.pack.jobs.types import CAP_JOBS, HostJob, HostState  # noqa: E402
from src.core.pack.machines import capabilities  # noqa: E402
from src.core.pack.machines.restrictions import Restrictions  # noqa: E402
from src.core.pack.placement import maintain  # noqa: E402
from src.core.pack.transport import blobs  # noqa: E402
from src.core.tmux_discovery import tmux_argv_prefix  # noqa: E402

COMPANY = "company-uid-0001"
CALLER_ROOT = "/Users/someone/caller dir"
VERBS = ("admit", "start", "status", "collect", "stop", "release")


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=True).stdout.strip()


class Machine:

    def __init__(self, tmp: Path, name: str, install_id: str) -> None:
        self.install_id = install_id
        self.state, self.projects, self.jobs = tmp / f"{name} state", tmp / f"{name} projects", tmp / f"{name} jobs"
        for folder in (self.state, self.projects, self.jobs):
            folder.mkdir()
        assert ensure_db_migrated(self.state).status == "ok"
        self.restrictions = Restrictions()
        self.app = FastAPI()
        self.app.include_router(transport_routes.router, prefix="/api/v1")
        self.app.include_router(jobs_routes.router, prefix="/api/v1")
        self.client: TestClient

    def conn(self):
        return connect(db_path_for(self.state), create=False)

    def grant_to(self, peer: str, principal_override: Any = None) -> None:
        with closing(self.conn()) as conn:
            if not any(g.peer_install_id == peer for g in grants.list_grants(conn)):
                key = fed_key.public_key_b64(fed_key.DeviceKey.from_seed(bytes([hash(peer) % 200 + 1]) * 32))
                grants.create_grant(conn, peer_install_id=peer, public_key=key, label=peer, scopes=("replica",))
            grant = next(g for g in grants.list_grants(conn) if g.peer_install_id == peer)
        principal = principal_override or peer_auth.Principal("peer", grant)
        for dep in (transport_routes._require_replica, jobs_routes._require_replica):
            self.app.dependency_overrides[dep] = lambda p=principal: p


@pytest.fixture()
def world(monkeypatch, tmp_path, tmux_test_socket):
    a, b = Machine(tmp_path, "a", "iid-a"), Machine(tmp_path, "b", "iid-b")
    current = [b]
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: current[0].state, raising=True)
    admitted: List[Any] = []
    refusal: List[Any] = [None]

    def fake_admit(work):
        admitted.append(work)
        return refusal[0]

    async def to_a(method: str, path: str, *, content: Any = None, headers: Any = None, json: Any = None):
        before, current[0] = current[0], a
        try:
            reply = a.client.request(method, "/api/v1" + path, content=content, headers=headers, json=json)
        finally:
            current[0] = before
        return reply.status_code, reply.json()

    host = Host(state_dir=b.state, jobs_root=b.jobs, install_id="iid-b", socket=tmux_test_socket, open_db=b.conn,
                restrictions=lambda: b.restrictions, live_agents=lambda: 0, admit=fake_admit, request_for=lambda iid: to_a)
    b.app.state.pack_jobs_host = host
    with ExitStack() as stack:
        a.client = stack.enter_context(TestClient(a.app))
        b.client = stack.enter_context(TestClient(b.app))
        a.grant_to("iid-b")
        b.grant_to("iid-a")
        uid = uuid.uuid4().hex
        with closing(b.conn()) as conn:
            replicas.accept_replica(conn, home_install_id="iid-a", project_uid=uid, name="tra der", root=str(b.projects / "tra der"),
                                    company_uid=COMPANY, company_name="acme")
        w = type("World", (), {})()
        w.a, w.b, w.host, w.uid, w.admitted, w.refusal, w.sock, w.tmp, w.jobs = a, b, host, uid, admitted, refusal, tmux_test_socket, tmp_path, []
        yield w
    for job_id in w.jobs:
        subprocess.run(tmux_argv_prefix(tmux_test_socket) + ["kill-session", "-t", "=" + paths.session_name(job_id)], capture_output=True, check=False)


def post(w, verb: str, body: Dict[str, Any]):
    return w.b.client.post(f"/api/v1/federation/pack/jobs/{verb}", json=body)


def make_snapshot(w, job_id: str) -> Dict[str, Any]:
    src = w.tmp / f"a repo {job_id}"
    src.mkdir()
    git(src, "init", "-q")
    (src / "f.txt").write_text("one\n")
    git(src, "add", "f.txt")
    git(src, "commit", "-q", "-m", "c1")
    (src / "f.txt").write_text("two\n")
    git(src, "commit", "-q", "-am", "snapshot")
    commit = git(src, "rev-parse", "HEAD")
    git(src, "update-ref", f"refs/heads/job-{job_id}", commit)
    bundle = w.tmp / f"{job_id}.bundle"
    bundle_io.make_bundle(str(src / ".git"), f"refs/heads/job-{job_id}", [], str(bundle))
    return {"commit": commit, "tree": git(src, "rev-parse", "HEAD^{tree}"), "blob_id": upload(w, bundle)}


def upload(w, path: Path) -> str:
    async def request(method: str, p: str, *, content: Any = None, headers: Any = None, json: Any = None):
        reply = w.b.client.request(method, "/api/v1" + p, content=content, headers=headers, json=json)
        return reply.status_code, reply.json()

    return asyncio.run(blobs.send_file(request, str(path), blob_id=blobs.new_id(), kind="bundle"))


def start_body(w, job_id: str, snap: Dict[str, Any], command: str, **extra: Any) -> Dict[str, Any]:
    body = {"job_id": job_id, "project_uid": w.uid, "snapshot_commit": snap["commit"], "snapshot_blob_id": snap["blob_id"], "scope": "",
            "kind": "suite", "dep_dirs": [], "command": command, "env": {}, "outputs": [], "time_cap_s": 60, "caller_roots": [CALLER_ROOT, "/Users/someone"]}
    body.update(extra)
    w.jobs.append(job_id)
    return body


def poll(w, job_id: str, want: set, secs: float = 40.0) -> Dict[str, Any]:
    end, last = time.monotonic() + secs, {}
    while time.monotonic() < end:
        reply = post(w, "status", {"job_id": job_id})
        assert reply.status_code == 200, reply.text
        last = reply.json()
        if last["state"] in want:
            return last
        time.sleep(0.2)
    raise AssertionError(f"job never reached {want}: {last}")


def run_to_exit(w, command: str = "echo hi; cat '/Users/someone/caller dir/f.txt'; echo new > out.txt; exit 3"):
    job_id = paths.new_job_id()
    snap = make_snapshot(w, job_id)
    assert post(w, "admit", {"job_id": job_id, "project_uid": w.uid, "kind": "suite", "est_cpu": 1.5, "est_ram_gb": 2.5}).status_code == 200
    reply = post(w, "start", start_body(w, job_id, snap, command))
    assert reply.status_code == 200 and reply.json() == {"ok": True, "state": "preparing"}, reply.text
    return job_id, snap, poll(w, job_id, {"exited", "failed"})


def test_capability_is_advertised() -> None:
    assert CAP_JOBS in capabilities.names()


def test_run_collect_release(world) -> None:
    w = world
    job_id, snap, st = run_to_exit(w)
    assert st["state"] == "exited" and st["exit_code"] == 3, st
    assert "hi" in st["output_tail"] and "two" in st["output_tail"]
    row = w.host.store.host_get(job_id)
    assert git(Path(row.slot_path), "rev-parse", "HEAD^{tree}") == snap["tree"]
    first = post(w, "collect", {"job_id": job_id}).json()
    assert first["changed"] == 1 and first["blob_id"] and first["result_commit"] != snap["commit"]
    assert bundle_io.received_path(w.a.state, first["blob_id"], sender="iid-b").exists()
    assert post(w, "collect", {"job_id": job_id}).json() == first
    root = w.b.projects / "tra der"
    assert git(root, "rev-parse", "refs/carnivore/jobs-base/iid-a") == git(root, "rev-parse", snap["commit"] + "^")
    assert post(w, "release", {"job_id": job_id}).status_code == 200
    assert [r["job_id"] for r in w.host.store.slot_rows(w.uid)] == [None]
    assert not (w.b.jobs / "meta" / job_id).exists()
    assert subprocess.run(["git", "-C", str(root), "rev-parse", "-q", "--verify", f"refs/carnivore/jobs/{job_id}/snapshot"], capture_output=True).returncode != 0
    assert git(root, "rev-parse", "refs/carnivore/jobs-base/iid-a")


def test_no_change_collects_no_blob(world) -> None:
    w = world
    job_id, snap, _ = run_to_exit(w, "exit 0")
    assert post(w, "collect", {"job_id": job_id}).json() == {"result_commit": snap["commit"], "blob_id": None, "changed": 0}


@pytest.mark.parametrize("flip", ["host_off", "project_list", "company_list"])
def test_every_route_runs_the_restrictions_gate(world, flip: str) -> None:
    w = world
    job_id, snap, _ = run_to_exit(w, "exit 0")
    w.b.restrictions = {"host_off": Restrictions(may_host_agents=False), "project_list": Restrictions(allowed_projects=["some-other-project"]),
                        "company_list": Restrictions(allowed_companies=["some-other-company"])}[flip]
    bodies = {"admit": {"job_id": job_id, "project_uid": w.uid, "kind": "suite"}, "start": start_body(w, job_id, snap, "exit 0")}
    for verb in VERBS:
        reply = post(w, verb, bodies.get(verb, {"job_id": job_id}))
        assert reply.status_code == 403 and reply.json()["detail"]["code"] == "pack_restricted", (verb, reply.text)


def test_owner_and_strangers_are_refused_on_every_route(world) -> None:
    w = world
    job_id, snap, _ = run_to_exit(w, "exit 0")
    bodies = {"admit": {"job_id": job_id, "project_uid": w.uid, "kind": "suite"}, "start": start_body(w, job_id, snap, "exit 0")}
    w.b.grant_to("iid-a", principal_override=peer_auth.OWNER)
    for verb in VERBS:
        reply = post(w, verb, bodies.get(verb, {"job_id": job_id}))
        assert reply.status_code == 403 and reply.json()["detail"]["code"] == "peer_token_required", (verb, reply.text)
    w.b.grant_to("iid-x")
    for verb in ("admit", "start"):
        reply = post(w, verb, bodies[verb])
        assert reply.status_code == 403 and reply.json()["detail"]["code"] == "not_a_counterpart", (verb, reply.text)
    for verb in ("status", "collect", "stop", "release"):
        assert post(w, verb, {"job_id": job_id}).status_code == 404, verb


def test_counterpart_rule_applies_even_when_the_row_exists(world) -> None:
    w = world
    job_id, _, _ = run_to_exit(w, "exit 0")
    w.host.store.host_set(job_id, project_uid=uuid.uuid4().hex)
    reply = post(w, "status", {"job_id": job_id})
    assert reply.status_code == 409 and reply.json()["detail"]["code"] == "project_not_here"


def test_unknown_project_and_admission(world) -> None:
    w = world
    job_id = paths.new_job_id()
    reply = post(w, "admit", {"job_id": job_id, "project_uid": uuid.uuid4().hex, "kind": "suite"})
    assert reply.status_code == 409 and reply.json()["detail"]["code"] == "project_not_here"
    assert post(w, "admit", {"job_id": job_id, "project_uid": w.uid, "kind": "browser", "est_cpu": 2.5, "est_ram_gb": 3.5}).status_code == 200
    assert (w.admitted[-1].kind, w.admitted[-1].est_cpu_cores, w.admitted[-1].est_ram_gb) == ("browser", 2.5, 3.5)
    snap = make_snapshot(w, job_id)
    w.refusal[0] = "system is pegged, try later"
    start = start_body(w, job_id, snap, "exit 0", kind="browser", est_cpu=2.5, est_ram_gb=3.5)
    for verb, body in (("admit", {"job_id": job_id, "project_uid": w.uid, "kind": "suite"}), ("start", start)):
        reply = post(w, verb, body)
        assert reply.status_code == 503 and reply.json()["detail"]["code"] == "host_busy", (verb, reply.text)
    assert (w.admitted[-1].kind, w.admitted[-1].est_cpu_cores, w.admitted[-1].est_ram_gb) == ("browser", 2.5, 3.5)
    assert w.host.store.host_get(job_id) is None


def test_start_refused_when_all_slots_are_busy(world) -> None:
    w = world
    for n in range(3):
        assert w.host.store.slot_claim(w.uid, str(w.b.projects), lambda i: str(w.tmp / f"busy {i}"), f"job_00000000000{n}") is not None
    job_id = paths.new_job_id()
    snap = make_snapshot(w, job_id)
    for verb, body in (("admit", {"job_id": job_id, "project_uid": w.uid, "kind": "light"}), ("start", start_body(w, job_id, snap, "exit 0"))):
        reply = post(w, verb, body)
        assert reply.status_code == 409 and reply.json()["detail"]["code"] == "no_free_slot", (verb, reply.text)


def test_bad_bundle_leaves_no_row(world) -> None:
    w = world
    job_id = paths.new_job_id()
    junk = w.tmp / "junk.bundle"
    junk.write_bytes(b"not a bundle at all")
    snap = {"commit": "a" * 40, "blob_id": upload(w, junk)}
    reply = post(w, "start", start_body(w, job_id, snap, "exit 0"))
    assert reply.status_code == 409 and reply.json()["detail"]["code"] == "bundle_unverified", reply.text
    assert w.host.store.host_get(job_id) is None
    reply = post(w, "start", start_body(w, job_id, {**snap, "blob_id": "b-0123456789ab"}, "exit 0"))
    assert reply.status_code >= 400 and w.host.store.host_get(job_id) is None


def test_stop_kills_the_sleeper_and_keeps_the_slot(world) -> None:
    w = world
    job_id = paths.new_job_id()
    snap = make_snapshot(w, job_id)
    assert post(w, "start", start_body(w, job_id, snap, "sleep 300")).status_code == 200
    poll(w, job_id, {"running"})
    pids = runner.pane_pids(socket=w.sock)
    assert pids and set(pids) <= set(maintain.throttle_roots(type("Panes", (), {"loose": staticmethod(lambda: [])})(), jobs_socket=w.sock))
    assert post(w, "stop", {"job_id": job_id, "keep_files": True}).status_code == 200
    assert post(w, "status", {"job_id": job_id}).json()["state"] == "stopped"
    assert not runner.alive(job_id, socket=w.sock)
    slot = w.host.store.slot_rows(w.uid)[0]
    assert slot["job_id"] is None and slot["keep_until"] is not None and Path(slot["path"]).exists()
    assert post(w, "release", {"job_id": job_id}).status_code == 200
    assert w.host.store.slot_rows(w.uid)[0]["keep_until"] is not None


def test_throttle_roots_without_agents(monkeypatch, world) -> None:
    w = world
    panes = type("Panes", (), {"loose": staticmethod(lambda: [])})()
    job_id = paths.new_job_id()
    snap = make_snapshot(w, job_id)
    assert post(w, "start", start_body(w, job_id, snap, "sleep 300")).status_code == 200
    poll(w, job_id, {"running"})
    assert maintain.throttle_roots(panes, jobs_socket=w.sock) == runner.pane_pids(socket=w.sock) != []
    post(w, "stop", {"job_id": job_id})


def test_recover_fails_preparing_rows(world) -> None:
    w = world
    claim = w.host.store.slot_claim(w.uid, str(w.b.projects), lambda i: str(w.tmp / f"slot {i}"), "job_aaaaaaaaaaaa")
    w.host.store.host_put(HostJob(job_id="job_aaaaaaaaaaaa", caller_install="iid-a", project_uid=w.uid, state=HostState.PREPARING, slot_path=claim[1]))
    assert w.host.recover() == 1
    row = w.host.store.host_get("job_aaaaaaaaaaaa")
    assert row.state == HostState.FAILED and "restarted" in row.detail
    assert folders.busy_count(w.host.store, w.uid) == 0


def test_sweep_purges_old_ended_rows(world) -> None:
    w = world
    job_id, _, _ = run_to_exit(w, "exit 0")
    w.host.sweep(time.time())
    assert w.host.store.host_get(job_id) is not None
    w.host.store.host_set(job_id, ended_at=time.time() - 2 * 86400)
    w.host.sweep(time.time())
    assert w.host.store.host_get(job_id) is None and not (w.b.jobs / "meta" / job_id).exists()
    assert folders.busy_count(w.host.store, w.uid) == 0


def test_throttle_roots_survives_tmux_trouble_on_the_jobs_socket(monkeypatch) -> None:
    from src.core.pack.jobs.types import JobError
    from src.core.tmux_discovery import TmuxVersionSkewError

    panes = type("Panes", (), {"loose": staticmethod(lambda: [7])})()

    def skew(_socket: str):
        raise TmuxVersionSkewError("x", None, None, None, ())

    monkeypatch.setattr(runner, "tmux_argv_prefix", skew)
    with pytest.raises(JobError) as exc:
        runner.alive("job_0000000000aa", socket="nosuch-socket")
    assert exc.value.code == "tmux_skew"
    assert maintain.throttle_roots(panes, jobs_socket="nosuch-socket") == [7]


def test_status_of_a_running_row_whose_session_vanished_fails_it_and_frees_the_slot(world) -> None:
    w = world
    job_id = paths.new_job_id()
    snap = make_snapshot(w, job_id)
    assert post(w, "start", start_body(w, job_id, snap, "sleep 300")).status_code == 200
    poll(w, job_id, {"running"})
    subprocess.run(tmux_argv_prefix(w.sock) + ["kill-session", "-t", "=" + paths.session_name(job_id)], capture_output=True, check=False)
    assert poll(w, job_id, {"failed"})["state"] == "failed"
    assert w.host.store.host_get(job_id).state == HostState.FAILED
    assert folders.busy_count(w.host.store, w.uid) == 0
