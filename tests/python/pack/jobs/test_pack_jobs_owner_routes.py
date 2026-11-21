
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest
from fastapi import FastAPI, HTTPException

# ruff: noqa: E402
from src.api import pack_jobs_routes as routes
from src.api import project_replica_routes
from src.api.auth import require_auth
from src.core.pack.jobs import boot, copy_run, place, replicas
from src.core.pack.jobs.types import CAP_JOBS
from src.core.pack.placement import rule
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import JobError, JobRecord, JobState

UID = "uid12345678"
ME = "iid-me"
PROJECT = {"uid": UID, "display_name": "trader", "root": "/p/trader"}


class FakeEngine:

    def __init__(self, store: JobStore) -> None:
        self.store, self.calls = store, []

    async def submit(self, req: Any) -> JobRecord:
        self.calls.append(("submit", req))
        if req.command == "refuse":
            raise JobError("unmet_requirement", "no", 409)
        return self.store.create_job(JobRecord(id="job_000000000001", project_name="trader", state=JobState.RUNNING, peer_label="studio",
                                               request_json=json.dumps({"request": {"command": req.command, "folder": req.folder, "kind": req.kind}})))

    def get(self, job_id: str):
        return self.store.get_job(job_id)

    def list(self, *, limit: int = 50, project_uid=None, live_only: bool = False):
        self.calls.append(("list", limit, project_uid, live_only))
        return self.store.list_jobs(limit=limit, project_uid=project_uid, live_only=live_only)

    async def wait(self, job_id: str, timeout_s: float):
        self.calls.append(("wait", job_id, timeout_s))
        return self.store.get_job(job_id)

    async def stop(self, job_id: str):
        self.calls.append(("stop", job_id))
        return self.store.set_state(job_id, JobState.STOPPED)


@pytest.fixture()
def eng(tmp_path: Path, monkeypatch) -> FakeEngine:
    fake = FakeEngine(JobStore(tmp_path / "state"))
    monkeypatch.setattr(boot, "engine", lambda: fake)
    monkeypatch.setattr(routes, "_read_project", lambda name: {
        "project": PROJECT, "install_id": ME, "label": "mini", "role": "home", "refusal": None, "other": None,
        "replicas": [{"install_id": "iid-auto", "label": "studio", "root": "/r/trader", "created_at": 5.0},
                     {"install_id": "iid-hand", "label": "tower", "root": "/h/trader", "created_at": 6.0}]})
    monkeypatch.setattr(routes.bundles, "is_repo", lambda path: True)
    return fake


def _client(auth: bool = True) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    if auth:
        app.dependency_overrides[require_auth] = lambda: None
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def _job(store: JobStore, state: JobState = JobState.RUNNING, job_id: str = "job_000000000009") -> None:
    store.create_job(JobRecord(id=job_id, project_uid=UID, state=state))


@pytest.mark.asyncio
async def test_401_without_auth(eng):
    async with _client(auth=False) as c:
        assert (await c.get("/api/v1/pack/jobs")).status_code in (401, 403)
        assert (await c.put(f"/api/v1/projects/trader/auto-delegate", json={"on": True})).status_code in (401, 403)


@pytest.mark.asyncio
async def test_post_list_get_wait_stop(eng):
    async with _client() as c:
        made = (await c.post("/api/v1/pack/jobs", json={"command": "pytest -q", "folder": "/p/trader", "time_cap_minutes": 2})).json()["job"]
        assert made["computer"] == "studio" and made["command"] == "pytest -q"
        req = eng.calls[0][1]
        assert req.time_cap_s == 120 and req.kind != "light" and req.caller_session is None
        listed = (await c.get("/api/v1/pack/jobs?limit=5&live=true")).json()
        assert listed["jobs"][0]["id"] == made["id"] and listed["jobs"][0]["side"] == "caller" and listed["next_before"] is None
        assert (await c.get(f"/api/v1/pack/jobs/{made['id']}")).json()["job"]["state"] == "running"
        assert not any(call[0] == "wait" for call in eng.calls)
        await c.get(f"/api/v1/pack/jobs/{made['id']}?wait=7")
        assert ("wait", made["id"], 7.0) in eng.calls
        assert (await c.get(f"/api/v1/pack/jobs/{made['id']}?wait=91")).status_code == 422
        assert (await c.post(f"/api/v1/pack/jobs/{made['id']}/stop")).json()["job"]["state"] == "stopped"
        stop_again = await c.post(f"/api/v1/pack/jobs/{made['id']}/stop")
        assert stop_again.status_code == 409 and stop_again.json()["detail"]["code"] == "job_finished"
        gone = await c.get("/api/v1/pack/jobs/job_00000000dead")
        assert gone.status_code == 404 and gone.json()["detail"]["code"] == "unknown_job"
        assert (await c.post("/api/v1/pack/jobs/job_00000000dead/stop")).status_code == 404


@pytest.mark.asyncio
async def test_post_refusals(eng):
    async with _client() as c:
        rel = await c.post("/api/v1/pack/jobs", json={"command": "x", "folder": "relative/dir"})
        assert rel.status_code == 422 and rel.json()["detail"]["code"] == "folder_not_absolute"
        refused = await c.post("/api/v1/pack/jobs", json={"command": "refuse", "folder": "/p"})
        assert refused.status_code == 409 and refused.json()["detail"]["code"] == "job_refused"
        assert (await c.post("/api/v1/pack/jobs", json={"command": "x", "folder": "/p", "bogus": 1})).status_code == 422


@pytest.mark.asyncio
async def test_put_on_starts_ensure_all(eng, monkeypatch):
    seen: List[Dict[str, Any]] = []

    async def fake_ensure_all(name, uid, **kw):
        seen.append({"name": name, "uid": uid, "policy": kw["policy"]})
        return {}

    monkeypatch.setattr(replicas, "ensure_all", fake_ensure_all)
    monkeypatch.setattr(place, "live_view", lambda root, uid: place.PlaceView(_peer(ME, "mini")))
    async with _client() as c:
        out = (await c.put("/api/v1/projects/trader/auto-delegate", json={"on": True, "never_use": ["tower"], "carry": ["a"]})).json()
        for task in list(routes._HELD):
            await task
        assert out["replicas"] == "starting" and out["auto_delegate"] is True and out["never_use"] == ["tower"]
        assert seen[0]["uid"] == UID and seen[0]["policy"].auto_delegate is True and seen[0]["policy"].never_use == ["tower"]
        got = (await c.get("/api/v1/projects/trader/auto-delegate")).json()
        assert got["project_uid"] == UID and got["carry"] == ["a"]


@pytest.mark.asyncio
async def test_put_refusals(eng, monkeypatch):
    def no_peer(machine: str):
        raise HTTPException(404, {"code": "unknown_machine", "detail": machine})

    monkeypatch.setattr(project_replica_routes, "find_peer", no_peer)
    async with _client() as c:
        monkeypatch.setattr(routes.bundles, "is_repo", lambda path: False)
        r = await c.put("/api/v1/projects/trader/auto-delegate", json={"on": True})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "not_a_repo"
        monkeypatch.setattr(routes.bundles, "is_repo", lambda path: True)
        r = await c.put("/api/v1/projects/trader/auto-delegate", json={"on": False, "keep": "nowhere"})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "keep_unknown"
        assert (await c.put("/api/v1/projects/trader/auto-delegate", json={"on": False, "keep": "mini"})).status_code == 200
        _job(eng.store)
        r = await c.put("/api/v1/projects/trader/auto-delegate", json={"on": False})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "jobs_running"
        _job(eng.store, JobState.DONE, "job_00000000000a")
        eng.store.set_state("job_000000000009", JobState.STOPPED)
        assert (await c.put("/api/v1/projects/trader/auto-delegate", json={"on": False})).status_code == 200


@pytest.mark.asyncio
async def test_wipe_touches_only_auto_replicas(eng, monkeypatch):
    removed: List[tuple] = []

    async def fake_remove(name: str, machine: str):
        removed.append((name, machine))
        if machine == "iid-bad":
            raise HTTPException(502, {"code": "peer_unreachable", "detail": "x"})
        return {}

    monkeypatch.setattr(project_replica_routes, "remove_project_replica", fake_remove)
    eng.store.auto_replica_add(UID, "iid-auto")
    eng.store.auto_replica_add(UID, "iid-bad")
    async with _client() as c:
        out = (await c.put("/api/v1/projects/trader/auto-delegate", json={"on": False, "wipe_others": True})).json()
    assert sorted(removed) == [("trader", "iid-auto"), ("trader", "iid-bad")]
    assert all(m != "iid-hand" for _, m in removed)
    assert out["unregistered"] == ["studio"] and out["left"] == [{"computer": "studio", "root": "/r/trader"}]
    assert out["failed"] == [{"computer": "iid-bad", "code": "peer_unreachable"}] and out["replicas"] == "unchanged"
    assert eng.store.auto_replica_list(UID) == ["iid-bad"]


@pytest.mark.asyncio
async def test_a_bad_list_is_a_422_with_a_catalog_code(eng):
    async with _client() as c:
        for body in ({"on": False, "bring_back": ["/abs"]}, {"on": True, "never_use": [""]}, {"on": True, "carry": ["../y"]}):
            reply = await c.put("/api/v1/projects/trader/auto-delegate", json=body)
            assert reply.status_code == 422 and reply.json()["detail"]["code"] == "bad_list", (body, reply.text)
        assert (await c.get("/api/v1/pack/jobs?limit=0")).json()["detail"]["code"] == "bad_limit"
        assert (await c.get("/api/v1/pack/jobs/x?wait=99")).json()["detail"]["code"] == "bad_wait"


def _peer(iid: str, label: str, may_host: bool = True) -> rule.MachineInput:
    return rule.MachineInput(iid, label, {"restrictions": {"may_host_agents": may_host}}, True, False, False, True, None)


@pytest.mark.asyncio
async def test_get_view_states_and_copy_run(eng, monkeypatch):
    peers = [_peer("iid-auto", "studio"), _peer("iid-odin", "odin"), _peer("iid-nw", "nowork", may_host=False)]
    monkeypatch.setattr(place, "live_view", lambda root, uid: place.PlaceView(_peer(ME, "mini"), peers, {p.install_id: [CAP_JOBS] for p in peers}))
    added: List[Any] = []

    async def fake_add(name: str, body: Any) -> None:
        added.append(body)
        if body.machine == "iid-auto":
            raise HTTPException(409, {"code": "project_name_taken", "detail": "taken"})

    monkeypatch.setattr(replicas, "_default_add", lambda: fake_add)
    monkeypatch.setattr(replicas, "_default_has", lambda uid, iid: False)
    pushed: List[int] = []
    monkeypatch.setattr(routes.home, "notify_changed", lambda: pushed.append(1))
    async with _client() as c:
        got = (await c.get("/api/v1/projects/trader/auto-delegate")).json()
        assert got["role"] == "home" and got["this_computer"] == {"install_id": ME, "label": "mini"} and got["is_repo"] is True
        assert got["live_jobs"] == 0 and got["copy_run"] == {"running": False, "refused": {}, "error": None}
        assert got["copies"] == [{"install_id": "iid-auto", "label": "studio", "auto": False, "root": "/r/trader"},
                                 {"install_id": "iid-hand", "label": "tower", "auto": False, "root": "/h/trader"}]
        eng.store.auto_replica_add(UID, "iid-auto")
        _job(eng.store)
        got = (await c.get("/api/v1/projects/trader/auto-delegate")).json()
        assert got["live_jobs"] == 1 and got["copies"][0]["auto"] is True and got["copies"][1]["auto"] is False
        monkeypatch.setattr(routes.bundles, "is_repo", lambda path: False)
        assert (await c.get("/api/v1/projects/trader/auto-delegate")).json()["is_repo"] is False
        monkeypatch.setattr(routes.bundles, "is_repo", lambda path: True)
        eng.store.set_state("job_000000000009", JobState.STOPPED)
        put = (await c.put("/api/v1/projects/trader/auto-delegate", json={"on": True})).json()
        assert put["this_computer"]["label"] == "mini" and put["replicas"] == "starting" and pushed[:1] == [1]
        for task in list(routes._HELD):
            await task
        run = (await c.get("/api/v1/projects/trader/auto-delegate")).json()["copy_run"]
        assert run == {"running": False, "refused": {"iid-auto": "project_name_taken"}, "error": None}
        assert sorted(b.machine for b in added) == ["iid-auto", "iid-odin"] and len(pushed) == 2
        monkeypatch.setattr(place, "live_view", lambda root, uid: (_ for _ in ()).throw(JobError("pack_not_running", "x", 503)))
        await c.put("/api/v1/projects/trader/auto-delegate", json={"on": True})
        for task in list(routes._HELD):
            await task
        assert copy_run.get(UID) == {"running": False, "refused": {}, "error": "pack_not_running"} and len(pushed) == 4
        refusal = HTTPException(409, {"code": "not_project_home", "detail": "replica"})
        monkeypatch.setattr(routes, "_read_project", lambda name: {"project": PROJECT, "role": "copy", "refusal": refusal, "other": "tower"})
        assert (await c.get("/api/v1/projects/trader/auto-delegate")).json() == {"role": "copy", "home_computer": "tower"}
        r = await c.put("/api/v1/projects/trader/auto-delegate", json={"on": True})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "not_project_home"
        monkeypatch.setattr(routes, "_read_project", lambda name: {"project": PROJECT, "role": "moved", "refusal": refusal, "other": "odin"})
        assert (await c.get("/api/v1/projects/trader/auto-delegate")).json() == {"role": "moved", "moved_to": "odin"}


@pytest.mark.asyncio
async def test_off_then_on_re_attaches_the_detached_folder(eng, monkeypatch):
    async def fake_remove(name: str, machine: str):
        return {}

    monkeypatch.setattr(project_replica_routes, "remove_project_replica", fake_remove)
    eng.store.auto_replica_add(UID, "iid-auto")
    async with _client() as c:
        await c.put("/api/v1/projects/trader/auto-delegate", json={"on": False, "wipe_others": True})
    assert eng.store.detached_get(UID, "iid-auto") == "/r/trader"
    bodies: List[Any] = []

    async def fake_add(name: str, body: Any) -> None:
        bodies.append(body)

    monkeypatch.setattr(replicas, "_default_add", lambda: fake_add)
    monkeypatch.setattr(replicas, "_default_has", lambda uid, iid: False)
    peers = [_peer("iid-auto", "studio")]
    monkeypatch.setattr(place, "live_view", lambda root, uid: place.PlaceView(_peer(ME, "mini"), peers, {"iid-auto": [CAP_JOBS]}))
    async with _client() as c:
        await c.put("/api/v1/projects/trader/auto-delegate", json={"on": True})
        for task in list(routes._HELD):
            await task
    assert [(b.machine, b.root) for b in bodies] == [("iid-auto", "/r/trader")] and eng.store.detached_get(UID, "iid-auto") is None


def test_overlapping_copy_runs_keep_running_until_the_last_ends():
    copy_run.start("ovl")
    copy_run.start("ovl")
    copy_run.finish("ovl", {"a": "project_name_taken"})
    assert copy_run.get("ovl") == {"running": True, "refused": {"a": "project_name_taken"}, "error": None}
    copy_run.finish("ovl", {"a": "present", "b": "created"})
    assert copy_run.get("ovl") == {"running": False, "refused": {}, "error": None}


@pytest.mark.asyncio
async def test_turning_the_mark_off_mid_run_stops_more_copies(eng, monkeypatch):
    peers = [_peer("iid-a", "a"), _peer("iid-b", "b")]
    view = place.PlaceView(_peer(ME, "mini"), peers, {p.install_id: [CAP_JOBS] for p in peers})
    routes.policy.set_auto(eng.store, UID, True)
    made: List[str] = []

    async def fake_add(name: str, body: Any) -> None:
        made.append(body.machine)
        routes.policy.set_auto(eng.store, UID, False)

    monkeypatch.setattr(replicas, "_default_has", lambda uid, iid: False)
    out = await replicas.ensure_all("trader", UID, store=eng.store, view=view, policy=routes.policy.get(eng.store, UID), add=fake_add)
    assert made == ["iid-a"] and list(out) == ["iid-a"]


@pytest.mark.asyncio
async def test_ensure_all_leaves_out_a_computer_the_master_rule_rejects_and_a_never_use_one(eng):
    peers = [_peer("iid-a", "a"), _peer("iid-b", "b"), _peer("iid-c", "c")]
    view = place.PlaceView(_peer(ME, "mini"), peers, {p.install_id: [CAP_JOBS] for p in peers}, "iid-a")
    routes.policy.set_auto(eng.store, UID, True)
    routes.policy.set_lists(eng.store, UID, never_use=["iid-c"], carry=None, bring_back=None)
    out = await replicas.ensure_all("trader", UID, store=eng.store, view=view, policy=routes.policy.get(eng.store, UID),
                                    add=lambda n, b: _noop(), has=lambda uid, iid: False)
    assert out == {"iid-a": "created"}


async def _noop() -> None:
    return None


@pytest.mark.asyncio
async def test_a_stale_kept_folder_is_forgotten_after_one_refusal_and_each_computer_gets_only_its_own(eng, monkeypatch):
    routes.policy.set_auto(eng.store, UID, True)
    eng.store.detached_set(UID, "iid-a", "/old/trader")
    sent: List[Any] = []

    async def fake_add(name: str, body: Any) -> None:
        sent.append((body.machine, body.root))
        if body.machine == "iid-a":
            raise HTTPException(409, {"code": "project_name_taken", "detail": "taken"})

    peers = [_peer("iid-a", "a"), _peer("iid-b", "b")]
    view = place.PlaceView(_peer(ME, "mini"), peers, {p.install_id: [CAP_JOBS] for p in peers})
    out = await replicas.ensure_all("trader", UID, store=eng.store, view=view, policy=routes.policy.get(eng.store, UID),
                                    add=fake_add, has=lambda uid, iid: False)
    assert sent == [("iid-a", "/old/trader"), ("iid-b", None)] and out["iid-a"] == "project_name_taken"
    assert eng.store.detached_get(UID, "iid-a") is None


@pytest.mark.asyncio
async def test_real_read_project_roles_and_a_copy_get_without_a_ready_engine(monkeypatch):
    refusal = HTTPException(409, {"code": "not_project_home", "detail": "replica"})
    monkeypatch.setattr(boot, "engine", lambda: (_ for _ in ()).throw(JobError("jobs_not_ready", "x", 503)))
    monkeypatch.setattr(routes, "_read_project", lambda name: {"project": PROJECT, "role": "copy", "refusal": refusal, "other": "tower"})
    monkeypatch.setattr(routes.bundles, "is_repo", lambda path: False)
    async with _client() as c:
        assert (await c.get("/api/v1/projects/trader/auto-delegate")).json() == {"role": "copy", "home_computer": "tower"}
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.put("/api/v1/projects/trader/auto-delegate", json={"on": True}, headers={"Authorization": "Bearer cak_abcdef"})
        assert r.status_code == 403 and r.json()["detail"]["code"] == "mark_owner_only"
