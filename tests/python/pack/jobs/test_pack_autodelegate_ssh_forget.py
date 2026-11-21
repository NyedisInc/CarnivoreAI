
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import httpx
import pytest
from fastapi import FastAPI

from src.api import pack_jobs_routes as routes
from src.api.auth import require_auth
from src.core.pack.jobs import boot, policy, wipe
from src.core.pack.jobs.ssh import far_script, owner
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import JobError, JobRecord, JobState

UID, OTHER = "uid12345678", "uidother0000"
URL = "/api/v1/projects/trader/auto-delegate"


def _ans(*lines: str) -> far_script.FarAnswer:
    out = far_script.FarAnswer(rc=0)
    for line in lines:
        out.lines.append(line)
        key, _sp, value = line.partition(" ")
        out.fields[key] = value
    return out


class FarStub:

    def __init__(self) -> None:
        self.calls: List[Any] = []
        self.forget: Any = _ans("forgotten")
        self.sweep: Any = _ans("swept 0")

    async def _far(self, verb: str, values: Optional[Dict[str, str]] = None, **_kw: Any) -> far_script.FarAnswer:
        self.calls.append((verb, dict(values or {})))
        got = self.forget if verb == "forget" else self.sweep
        if isinstance(got, Exception):
            raise got
        return got


@pytest.fixture()
def world(tmp_path, monkeypatch):
    store = JobStore(tmp_path / "state")
    far = FarStub()
    for key in ("hostaaaa", "hostbbbb"):
        store.ssh_target_put(key, takes_work=1, pinned_fp="fp")
        store.ssh_seed_set(UID, key, "abc")
    store.ssh_seed_set(OTHER, "hostaaaa", "abc")
    project = {"uid": UID, "display_name": "trader", "root": str(tmp_path)}
    engine = SimpleNamespace(store=store, list=lambda **kw: store.list_jobs(limit=kw.get("limit", 50), project_uid=kw.get("project_uid"),
                                                                            live_only=kw.get("live_only", False)))
    monkeypatch.setattr(boot, "engine", lambda: engine)
    monkeypatch.setattr(routes, "_read_project", lambda name: {"project": project, "install_id": "me", "label": "mini", "role": "home",
                                                              "refusal": None, "other": None, "replicas": []})
    monkeypatch.setattr(routes.bundles, "is_repo", lambda path: True)
    monkeypatch.setattr(owner, "ssh_target_for", lambda key: far)

    async def host(key: str) -> Any:
        return SimpleNamespace(key=key, label="Box " + key[-1].upper())

    monkeypatch.setattr(wipe, "_ssh_host", host)
    policy.set_auto(store, UID, True)
    return SimpleNamespace(store=store, far=far, mp=monkeypatch)


async def _put(**body: Any) -> httpx.Response:
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return await c.put(URL, json={"on": False, "wipe_others": True, **body})


@pytest.mark.asyncio
async def test_delete_set_forgets_the_project_on_each_ssh_computer(world):
    r = await _put(delete_copies=True, delete_only=[])
    assert r.status_code == 200
    body = r.json()
    assert body["ssh_forgotten"] == [{"key": "hostaaaa", "label": "Box A", "code": "forgotten"}, {"key": "hostbbbb", "label": "Box B", "code": "forgotten"}]
    forgets = [c[1]["uid"] for c in world.far.calls if c[0] == "forget"]
    assert forgets == [UID, UID] and OTHER not in forgets
    assert body["ssh_holding"] == []
    assert world.store.ssh_seed_get(OTHER, "hostaaaa") is not None
    assert policy.get(world.store, UID).auto_delegate is False


@pytest.mark.asyncio
async def test_delete_unset_touches_nothing_far_and_the_answer_names_the_holders(world):
    r = await _put(wipe_others=True)
    assert r.status_code == 200 and world.far.calls == []
    assert r.json()["ssh_forgotten"] == []
    assert [h["key"] for h in r.json()["ssh_holding"]] == ["hostaaaa", "hostbbbb"]
    assert (await _put()).json()["ssh_holding"][0]["label"] == "Box A"


@pytest.mark.asyncio
async def test_a_far_side_that_fails_is_reported_and_the_turn_off_completes(world):
    world.far.forget = JobError("far_failed", "no", 502)
    r = await _put(delete_copies=True, delete_only=[])
    assert r.status_code == 200
    assert [x["code"] for x in r.json()["ssh_forgotten"]] == ["far_failed", "far_failed"]
    assert policy.get(world.store, UID).auto_delegate is False
    assert len(r.json()["ssh_holding"]) == 2


@pytest.mark.asyncio
async def test_a_live_job_of_this_project_refuses_that_computer_only_and_a_kept_slot_is_named(world):
    world.store.create_job(JobRecord(id="job_00000000a1b2", project_uid=OTHER, state=JobState.RUNNING, peer_install_id="ssh:hostaaaa"))
    world.far.forget = _ans("kept /far/folders/x/slot2", "forgotten")
    body = (await _put(delete_copies=True, delete_only=[])).json()
    assert [x["code"] for x in body["ssh_forgotten"]] == ["kept_slot", "kept_slot"]
    world.store.create_job(JobRecord(id="job_00000000a1b3", project_uid=UID, state=JobState.RUNNING, peer_install_id="ssh:hostbbbb"))
    assert (await wipe.forget_ssh(world.store, UID))[1]["code"] == "jobs_running"


@pytest.mark.asyncio
async def test_the_copy_check_names_the_ssh_computers_holding_a_copy(world):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(URL + "/copy-check")
    assert r.status_code == 200 and r.json()["copies"] == [] and [h["key"] for h in r.json()["ssh_holding"]] == ["hostaaaa", "hostbbbb"]


@pytest.mark.asyncio
async def test_a_failed_far_sweep_after_the_forget_keeps_the_forgotten_answer(world):
    world.far.sweep = JobError("far_failed", "sweep did not answer", 502)
    body = (await _put(delete_copies=True, delete_only=[])).json()
    assert [x["code"] for x in body["ssh_forgotten"]] == ["forgotten", "forgotten"]
    assert world.store.ssh_seed_get(UID, "hostaaaa") is None
