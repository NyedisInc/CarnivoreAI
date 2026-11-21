
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException

from src.core.pack.jobs import policy as policy_mod, replicas
from src.core.pack.jobs.place import PlaceView, place
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.target import PeerTarget
from src.core.pack.jobs.types import AdmitBody, CAP_JOBS, JobError
from src.core.pack.placement import rule
from src.core.pack.placement.workload import resolve
from src.core.federation.peer_client import PeerRefused, PeerUnreachable

A, B, C = "iid-a", "iid-b", "iid-c"
WORK = resolve({"kind": "suite"})


def snap(load1: float, *, may_host: bool = True) -> Dict[str, Any]:
    return {"load": {"cores": 10, "load_1": load1, "mem_total_gb": 32.0, "mem_available_gb": 28.0, "disk_free_gb": 200.0},
            "reserve": {"level": "away", "cpu_pct": 10, "mem_pct": 10}, "toolchain": {}, "restrictions": {"may_host_agents": may_host}}


def view(self_load: float, peers: List[rule.MachineInput], *, master: str = A, me: str = A, caps: Any = None) -> PlaceView:
    self_in = rule.MachineInput(me, "mac", snap(self_load, may_host=False), True, True, True, True, 0)
    return PlaceView(self_in, peers, caps if caps is not None else {p.install_id: [CAP_JOBS] for p in peers}, master)


def peer(iid: str, label: str, load: float = 1.0, **kw: Any) -> rule.MachineInput:
    return rule.MachineInput(iid, label, snap(load, **{k: kw.pop(k) for k in ("may_host",) if k in kw}), True, False, False, True, None)


@pytest.fixture()
def store(tmp_path) -> JobStore:
    return JobStore(tmp_path / "state")


def on(store: JobStore, **lists: Any) -> policy_mod.Policy:
    policy_mod.set_auto(store, "p1x23456", True)
    if lists:
        policy_mod.set_lists(store, "p1x23456", **lists)
    return policy_mod.get(store, "p1x23456")


def test_mark_off_answers_here(store):
    got = place(WORK, "p1x23456", policy_mod.get(store, "p1x23456"), view(9.5, [peer(B, "tower")]))
    assert got.decision == "here" and got.reason == "project is set to this computer only"


def test_self_with_room_answers_here_even_when_its_own_switch_is_off(store):
    got = place(WORK, "p1x23456", on(store), view(1.0, [peer(B, "tower")]))
    assert got.decision == "here" and got.reason.startswith("this computer has room:")


def test_self_full_and_idle_peer_answers_remote(store):
    got = place(WORK, "p1x23456", on(store), view(9.5, [peer(B, "tower")]))
    assert (got.decision, got.peer_install_id, got.peer_label) == ("remote", B, "tower")


def test_dropped_peers_each_name_their_reason(store):
    v = view(9.5, [peer(B, "old"), peer(C, "nope")], caps={C: [CAP_JOBS]})
    got = place(WORK, "p1x23456", on(store, never_use=["nope"]), v)
    assert got.decision == "here"
    assert "old runs an older carnivore" in got.reason and "nope is on the never use list" in got.reason


def test_a_non_master_peer_is_dropped_when_self_is_not_master(store):
    v = view(9.5, [peer(B, "tower"), peer(C, "mini")], master=C, me=A)
    got = place(WORK, "p1x23456", on(store), v)
    assert (got.decision, got.peer_install_id) == ("remote", C)
    v = view(9.5, [peer(B, "tower")], master=C, me=A)
    got = place(WORK, "p1x23456", on(store), v)
    assert got.decision == "here" and "tower is not the master" in got.reason


def test_peer_that_may_not_host_is_not_chosen(store):
    got = place(WORK, "p1x23456", on(store), view(9.5, [peer(B, "tower", may_host=False)]))
    assert got.decision == "here" and "may_host_agents" in got.reason


def test_ensure_records_only_what_it_created(store):
    calls: List[str] = []

    async def add(name: str, body: Any) -> None:
        calls.append(body.machine)

    async def go() -> List[bool]:
        h = lambda uid, iid: iid == C  # noqa: E731
        return [await replicas.ensure("tra der", "p1x23456", B, store=store, add=add, has=h),
                await replicas.ensure("tra der", "p1x23456", C, store=store, add=add, has=h)]

    assert asyncio.run(go()) == [True, False]
    assert calls == [B] and policy_mod.auto_replicas(store, "p1x23456") == [B]


def test_ensure_all_maps_created_present_and_refusal(store):
    async def add(name: str, body: Any) -> None:
        if body.machine == "iid-d":
            raise HTTPException(409, {"code": "project_name_taken", "detail": "taken"})

    peers = [peer(B, "tower"), peer(C, "mini"), peer("iid-d", "studio"), peer("iid-e", "old")]
    v = view(9.5, peers, caps={B: [CAP_JOBS], C: [CAP_JOBS], "iid-d": [CAP_JOBS]})
    got = asyncio.run(replicas.ensure_all("tra der", "p1x23456", store=store, view=v, policy=on(store), add=add,
                                          has=lambda uid, iid: iid == C))
    assert got == {B: "created", C: "present", "iid-d": "project_name_taken"}


def test_ensure_all_never_copies_a_project_to_an_ssh_computer(store):
    calls: List[str] = []

    async def add(name: str, body: Any) -> None:
        calls.append(body.machine)

    ssh = "ssh:target-key"
    v = view(9.5, [peer(B, "tower"), peer(ssh, "box")], caps={B: [CAP_JOBS], ssh: [CAP_JOBS]})
    got = asyncio.run(replicas.ensure_all("tra der", "p1x23456", store=store, view=v, policy=on(store), add=add, has=lambda uid, iid: False))
    assert got == {B: "created"} and calls == [B]


def _target(result: Any) -> PeerTarget:
    async def request(method: str, path: str, *, json: Any = None, **kw: Any):
        if isinstance(result, BaseException):
            raise result
        return result

    return PeerTarget(B, "tower", request)


@pytest.mark.parametrize("failure", [PeerUnreachable("down"), PeerRefused("grant_invalid"), asyncio.TimeoutError(), OSError("x")])
def test_peer_target_maps_wire_failures_to_unreachable(failure):
    with pytest.raises(JobError) as err:
        asyncio.run(_target(failure).release("job_0123456789ab"))
    assert err.value.code == "unreachable" and err.value.status == 502


def test_peer_target_maps_a_refusal_and_a_bare_status():
    body = AdmitBody(job_id="job_0123456789ab", project_uid="p1x23456", kind="suite")
    with pytest.raises(JobError) as err:
        asyncio.run(_target((403, {"detail": {"code": "pack_restricted", "detail": "no"}})).admit(body))
    assert (err.value.code, err.value.status) == ("pack_restricted", 403)
    with pytest.raises(JobError) as err:
        asyncio.run(_target((500, None)).admit(body))
    assert err.value.code == "http_500"
    asyncio.run(_target((200, {})).admit(body))
