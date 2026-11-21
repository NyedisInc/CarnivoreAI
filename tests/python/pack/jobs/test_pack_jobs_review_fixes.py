
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import sqlite3
import stat
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import pack_installs_routes, pack_jobs_needs_routes
from src.api.auth import require_auth
from src.core.mcp import pack_jobs_tools as tools
from src.core.pack.jobs import boot, engine_run, install as inst, needs_model, paths, policy as policy_mod, prewarm
from src.core.pack.jobs.install import Installer
from src.core.pack.jobs.place import PlaceView, install_candidates
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import CAP_JOBS, CAP_NEEDS, JobError, JobRecord, JobState
from src.core.pack.machines import restrictions as restrictions_mod
from src.core.pack.placement.needs import parse_need
from tests.python.pack.jobs import test_pack_jobs_install as base
from tests.python.pack.jobs.test_pack_jobs_install import A, B, JOB, SUITE, UID, FakeTarget, lacking, machine, make_engine, snap, waiting_job
from tests.python.pack.jobs.test_pack_jobs_prewarm import FakeHost, arun, body, world  # noqa: F401


def new_installer(tmp_path: Path, store: JobStore, **kw: Any) -> Installer:
    brew = base.fake_brew(tmp_path, "exit 0")
    kw.setdefault("present", lambda _t: False)
    kw.setdefault("restrictions", lambda: restrictions_mod.Restrictions(may_install_tools=True))
    return Installer(store, tmp_path / "jobs", brew=lambda: brew, owns_job=lambda j, c: True, **kw)




def test_boot_build_makes_the_host_the_engine_and_an_installer(tmp_path, monkeypatch) -> None:
    from src.config import settings

    state, root = tmp_path / "state", tmp_path / "jobs"
    state.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state)
    monkeypatch.setattr(paths, "default_jobs_root", lambda: root)
    monkeypatch.setattr(paths, "check_root", lambda r: root)
    monkeypatch.setattr(boot, "_install_id", lambda _s: "iid-me")
    monkeypatch.setattr(boot, "_built", {})
    the_host, the_engine = boot.build()
    assert the_host.install_id == "iid-me" and isinstance(boot._built["installer"], inst.Installer)
    assert boot._built["engine"] is the_engine
    owns = boot._built["installer"]._owns_job
    assert owns("job_nobody", "peer-a") is False




def test_an_install_never_upgrades_what_is_there(tmp_path) -> None:
    store = JobStore(tmp_path / "state")
    assert inst.BREW_FLAGS["HOMEBREW_NO_INSTALL_UPGRADE"] == "1" and inst.brew_env()["HOMEBREW_NO_INSTALL_UPGRADE"] == "1"
    ins = new_installer(tmp_path, store, present=lambda t: t == "node")
    with pytest.raises(JobError) as err:
        asyncio.run(ins.request("peer-a", JOB, ["node"]))
    assert err.value.code == "already_present" and store.install_list(10) == []


def test_a_batch_cannot_go_past_five_installs_a_day(tmp_path) -> None:
    store = JobStore(tmp_path / "state")
    for n in range(4):
        store.install_put(inst.InstallRow(id=f"ins_00000000000{n}", tool="gh", formula="gh", caller_install="peer-a", job_id=f"x{n}", state="done",
                                          started_at=time.time()))
    ins = new_installer(tmp_path, store)
    with pytest.raises(JobError) as err:
        asyncio.run(ins.request("peer-a", JOB, ["ffmpeg", "node", "gh", "python3.12"]))
    assert err.value.code == "install_limit" and len(store.install_list(50)) == 4


def test_a_queued_install_does_not_run_after_the_switch_went_off(tmp_path) -> None:
    store = JobStore(tmp_path / "state")
    on = {"v": True}
    ins = new_installer(tmp_path, store, restrictions=lambda: restrictions_mod.Restrictions(may_install_tools=on["v"]))

    async def flow() -> Any:
        rows = await ins.request("peer-a", JOB, ["gh"])
        on["v"] = False
        while ins._tasks:
            await asyncio.gather(*list(ins._tasks))
        return rows

    rows = asyncio.run(flow())
    got = store.install_get(rows[0].id)
    assert got.state == "failed" and "stopped allowing" in got.tail and not (tmp_path / "argv.txt").exists()


def test_find_brew_takes_the_executable_file_owned_by_this_user_only(tmp_path, monkeypatch) -> None:
    plain, good = tmp_path / "plain-brew", tmp_path / "good-brew"
    plain.write_text("x")
    plain.chmod(0o644)
    good.write_text("#!/bin/sh\n")
    good.chmod(0o755)
    monkeypatch.setattr(inst, "BREW_PATHS", (str(tmp_path / "absent"), str(plain), str(good)))
    assert inst.find_brew() == str(good)
    monkeypatch.setattr(inst, "BREW_PATHS", (str(plain),))
    assert inst.find_brew() is None
    monkeypatch.setattr(os, "getuid", lambda: os.stat(good).st_uid + 1)
    monkeypatch.setattr(inst, "BREW_PATHS", (str(good),))
    assert inst.find_brew() is None


def test_install_text_is_cut_and_has_no_control_bytes() -> None:
    assert inst.clean_text("\x1b[2Jbad\x00 line") == "[2Jbad line" and len(inst.clean_text("a" * 5000)) == inst.TAIL_CHARS and inst.clean_text(None) == ""




def test_the_asker_holds_the_job_again_before_it_installs(tmp_path, monkeypatch) -> None:
    target = FakeTarget(["done"])
    eng = make_engine(tmp_path, PlaceView(machine(A, "mac", snap(), is_self=True), []), monkeypatch, target)
    rec = waiting_job(eng, ["ffmpeg"])
    asyncio.run(eng._install_first(rec, ["ffmpeg"]))
    assert [b.job_id for b in target.admitted] == [JOB] and target.admitted[0].needs is None


def test_a_target_that_says_running_for_ever_ends_in_a_plain_failure(tmp_path, monkeypatch) -> None:
    target = FakeTarget(["running"])
    eng = make_engine(tmp_path, PlaceView(machine(A, "mac", snap(), is_self=True), []), monkeypatch, target)
    rec = waiting_job(eng, ["ffmpeg"])
    now = {"t": 1000.0}
    eng._clock = lambda: now["t"]

    async def tick(_s: float) -> None:
        now["t"] += 60.0

    eng._sleep = tick
    with pytest.raises(JobError) as err:
        asyncio.run(eng._install_first(rec, ["ffmpeg"]))
    assert err.value.code == "install_failed" and "did not finish in time" in err.value.detail


@pytest.mark.parametrize("bad", ["../../machines/rescan?x=", "ins_" + "g" * 12, "x" * 10000])
def test_an_install_id_that_is_not_ins_and_12_hex_is_never_followed(tmp_path, monkeypatch, bad) -> None:
    target = FakeTarget(["done"])

    async def install(job_id: str, uid: str, names: List[str]) -> List[Dict[str, Any]]:
        return [{"id": bad, "tool": "ffmpeg", "state": "running"}]

    target.install = install
    eng = make_engine(tmp_path, PlaceView(machine(A, "mac", snap(), is_self=True), []), monkeypatch, target)
    with pytest.raises(JobError) as err:
        asyncio.run(eng._install_first(waiting_job(eng, ["ffmpeg"]), ["ffmpeg"]))
    assert err.value.code == "install_failed"


def test_the_target_text_reaches_the_agent_cleaned_and_cut(tmp_path, monkeypatch) -> None:
    target = FakeTarget(["failed"])

    async def status(install_id: str) -> Dict[str, Any]:
        return {"id": install_id, "tool": "\x1b[2Jevil", "state": "failed", "exit_code": 1, "tail": "\x1b[31m" + "A" * 5000}

    target.install_status = status
    eng = make_engine(tmp_path, PlaceView(machine(A, "mac", snap(), is_self=True), []), monkeypatch, target)
    with pytest.raises(JobError) as err:
        asyncio.run(eng._install_first(waiting_job(eng, ["ffmpeg"]), ["ffmpeg"]))
    assert "\x1b" not in err.value.detail and len(err.value.detail) < 500 and "evil" not in err.value.detail
    rec = JobRecord(id=JOB, state=JobState.HERE, error_detail="tower \x1b[2J" + "B" * 5000)
    shown = tools.agent_result(rec)["reason"]
    assert "\x1b" not in shown and len(shown) <= 300
    refused = tools.agent_result(JobRecord(id=JOB, state=JobState.REFUSED, error_code="x", error_detail="\x1b[2J" + "C" * 5000))
    assert "\x1b" not in refused["reason"] and len(refused["reason"]) <= 300




def test_only_program_looking_words_reach_the_model() -> None:
    assert needs_model.programs_of('"run the build token hunter2" --x') == []
    assert needs_model.programs_of("npx -y 'hunter2 secret arg'") == ["npx"]
    assert needs_model.programs_of("ffmpeg -i a b && node x.js") == ["ffmpeg", "node"]


def test_a_never_use_computer_is_not_offered_an_install() -> None:
    store = JobStore(Path(os.environ.get("TMPDIR", "/tmp")) / f"rf-{os.getpid()}-{time.time_ns()}")
    policy_mod.set_auto(store, UID, True)
    pol = policy_mod.get(store, UID)
    the_view = PlaceView(machine(A, "mac", snap(), is_self=True), [machine(B, "tower", lacking())], {B: [CAP_JOBS, CAP_NEEDS, inst.CAP_INSTALL]}, A)
    assert install_candidates(SUITE, UID, pol, the_view, needs=[parse_need("ffmpeg")]) is not None
    banned = dataclasses.replace(pol, never_use=[B])
    assert install_candidates(SUITE, UID, banned, the_view, needs=[parse_need("ffmpeg")]) is None




def _client(router: Any, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: None
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_an_api_key_cannot_install_a_tool_but_can_read_the_list(tmp_path, monkeypatch) -> None:
    ran: List[Any] = []

    class Fake:
        async def request(self, *a: Any, **k: Any) -> List[Any]:
            ran.append(a)
            return []

        def rows(self, limit: int) -> List[Any]:
            return []

        def can_install(self) -> bool:
            return False

    client = _client(pack_installs_routes.router, monkeypatch)
    client.app.state.pack_jobs_installer = Fake()
    key = {"Authorization": "Bearer cak_abcdef"}
    refused = client.post("/api/v1/pack/installs", json={"tool": "node"}, headers=key)
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "install_owner_only" and ran == []
    assert client.get("/api/v1/pack/installs", headers=key).status_code == 200
    assert client.post("/api/v1/pack/installs", json={"tool": "node"}, headers={"Authorization": "Bearer session-token"}).status_code == 200 and ran


def test_an_api_key_cannot_set_what_a_projects_jobs_need(monkeypatch) -> None:
    called: List[Any] = []
    monkeypatch.setattr(pack_jobs_needs_routes, "_uid", lambda name: called.append(name) or UID)
    client = _client(pack_jobs_needs_routes.router, monkeypatch)
    refused = client.put("/api/v1/projects/app/delegate-needs", json={"render": None}, headers={"Authorization": "Bearer cak_abcdef"})
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "needs_owner_only" and called == []




@arun
async def test_only_the_home_may_ask_for_a_prewarm(world) -> None:  # noqa: F811
    host = world.host
    got = await prewarm.prewarm(host, "peer-other", body(world.commit))
    assert got["ok"] is False and "home computer" in got["reason"] and host.store.slot_rows("uid12345abcd") == []
    host._gate_sync = lambda caller, uid, **_: {"root": str(world.repo), "air_gap": 0, "pack_state": "home", "home_install_id": "peer-a"}
    assert (await prewarm.prewarm(host, "peer-a", body(world.commit)))["ok"] is False


def test_two_projects_never_share_a_warm_up_marker() -> None:
    assert prewarm.marker("abcdefgh-one") != prewarm.marker("abcdefgh-two") and prewarm.marker("abcdefgh-one") == prewarm.marker("abcdefgh-one")


@arun
async def test_a_leftover_ended_row_does_not_block_or_hide_a_new_warm_up_and_the_hold_ends(world) -> None:  # noqa: F811
    from src.core.pack.jobs.types import HostJob, HostState
    from src.core.pack.reserve.holds import HOLDS

    host = world.host
    marker = prewarm.marker("uid12345abcd")
    host.store.host_put(HostJob(job_id=marker, caller_install="peer-a", project_uid="uid12345abcd", state=HostState.FAILED, snapshot_commit=world.commit))
    assert await prewarm.prewarm(host, "peer-a", body(world.commit)) == {"ok": True}
    assert host.store.host_get(marker).state == HostState.PREPARING
    assert HOLDS.owner(marker) == "peer-a"
    await asyncio.gather(*host.tasks)
    assert host.store.host_get(marker) is None and HOLDS.owner(marker) is None


@arun
async def test_a_warm_up_refuses_while_this_computer_does_not_know_its_own_load(world, monkeypatch) -> None:  # noqa: F811
    monkeypatch.setattr(prewarm.host_admit, "own_snapshot", lambda: None)
    got = await prewarm.prewarm(world.host, "peer-a", body(world.commit))
    assert got["ok"] is False and "own load" in got["reason"] and not world.host.tasks


def test_boot_keep_sync_asks_for_a_warm_up_only_while_a_delegate_would_run_without_a_card(tmp_path, monkeypatch) -> None:
    from src.config import settings
    from tests.python.beast_mode.grid import arm

    state, root = tmp_path / "state", tmp_path / "jobs"
    state.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state)
    monkeypatch.setattr(paths, "default_jobs_root", lambda: root)
    monkeypatch.setattr(paths, "check_root", lambda r: root)
    monkeypatch.setattr(boot, "_install_id", lambda _s: "iid-me")
    monkeypatch.setattr(boot, "_built", {})
    _host, the_engine = boot.build()
    flag = {"on": False}
    arm(monkeypatch, lambda: flag["on"])
    syncer = boot._keep_sync(the_engine)
    assert syncer._may_prewarm() is False
    flag["on"] = True
    assert syncer._may_prewarm() is True
    flag["on"] = False
    assert syncer._may_prewarm() is False
