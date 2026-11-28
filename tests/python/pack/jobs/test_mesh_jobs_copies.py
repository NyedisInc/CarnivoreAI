
from __future__ import annotations

import asyncio
import base64
import functools
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set

import pytest
from fastapi import HTTPException

from src.api import pack_jobs_routes, project_replica_routes, project_transport_routes, projects_service
from src.core.computers import mesh
from src.core.db import connect, db_path_for, set_meta
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import META_INSTALL_ID
from src.core.federation import mesh_peers, peer_links
from src.core.pack.identity import replicas as identity_replicas
from src.core.pack.jobs import copy_run, keep_sync, member_link, member_view, policy as policy_mod, replicas
from src.core.pack.jobs.member_view import Deps, MemberView
from src.core.pack.jobs.place import PlaceView
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import CAP_JOBS, JobError, JobRecord, JobState
from src.core.pack.machines import capabilities
from src.core.pack.machines import runtime as machines_runtime
from src.core.pack.machines.roster_v2 import RosterComputerV2, RosterV2
from src.core.pack.meshdata import gossip
from src.core.pack.placement import rule
from src.core.pack.relay import member_reach
from src.core.relay_identity.device_key import DeviceKey, b64url
from src.models.projects import AddReplicaRequest

UID = "uid-copies-0001"
B, A, S = "iid-b", "iid-a", "iid-s"
C, G, D, E, F, H, I, J, K = "iid-c", "iid-g", "iid-d", "iid-e", "iid-f", "iid-h", "iid-i", "iid-j", "iid-k"
CAPS = [CAP_JOBS, capabilities.CAP_JOBS_MESH]
CERT = base64.b64encode(b"x" * 40).decode()
ORDER = [A, B, C, G, D, E, F, H, I, J, K]
REGISTRY_CAPS: Dict[str, List[str]] = {C: CAPS, G: CAPS, D: CAPS, E: CAPS, H: CAPS, I: [CAP_JOBS], J: CAPS, K: CAPS}


def rich(iid: str, *, may_host: bool = True) -> Dict[str, Any]:
    return {"install_id": iid, "load": {"cores": 10, "load_1": 1.0, "mem_total_gb": 32.0, "mem_available_gb": 28.0, "disk_free_gb": 200.0},
            "reserve": {"level": "away", "cpu_pct": 10, "mem_pct": 10}, "toolchain": {}, "restrictions": {"may_host_agents": may_host},
            "can": {"v": 1, "brew": False, "tools": {}, "labels": []}, "pressure": {"v": 1, "pegged": False}}


class Registry:

    def __init__(self) -> None:
        self.clients: List[str] = []
        self.connects: List[str] = []

    def capabilities(self, iid: str) -> Optional[List[str]]:
        return REGISTRY_CAPS.get(iid)

    def client(self, iid: str) -> Any:
        self.clients.append(iid)
        return None

    async def connect(self, iid: str, *_a: Any) -> Any:
        self.connects.append(iid)
        return None


class StarLinks:

    def client(self, iid: str) -> Any:
        return None

    def capabilities(self, iid: str) -> List[str]:
        return []


class World:

    def __init__(self, tmp: Path, mp: pytest.MonkeyPatch) -> None:
        self.state = tmp / "state"
        ensure_db_migrated(self.state)
        self.now = [1000.0]
        self.one_way: Set[str] = {D}
        self.off: Set[str] = set()
        self.removed: Set[str] = set()
        self.unreadable = False
        self.link_off: Set[str] = {E}
        self.tries: List[str] = []
        self.reg = Registry()
        self.looks: List[Any] = []
        self.adds: List[str] = []
        self.carries: List[str] = []
        self.held = {C}
        self.refuse: Dict[str, Any] = {}
        self.answers: Dict[str, Any] = {C: (200, {"snapshot": rich(C), "project": "ok"}), G: (200, {"snapshot": rich(G), "project": "project_not_here"}),
                                        J: (200, {"snapshot": rich(J, may_host=False), "project": "project_not_here"})}
        self.on_demand = {H}
        self.cards = {i: {"age_s": 5} for i in (C, G, D, E, F, H, I, J)} | {K: {"age_s": member_view.CARD_MAX_AGE_S + 5}}
        with closing(self.db()) as conn:
            set_meta(conn, META_INSTALL_ID, B)
            conn.execute("INSERT INTO projects (root, raw_path, display_name, source, presence, created_at, updated_at, last_opened_at) "
                         "VALUES ('/r/p', '/r/p', 'P', 'user', 'present', 't', 't', 't')")
            conn.execute("UPDATE projects SET uid = ? WHERE root = '/r/p'", (UID,))
            identity_replicas.record_replica(conn, UID, C, "/r/p", "carried")
        self.store = JobStore(self.state)
        policy_mod.set_auto(self.store, UID, True)
        wired = SimpleNamespace(open_db=self.db, peers=lambda: [SimpleNamespace(install_id=A), SimpleNamespace(install_id=S)],
                                runtime=SimpleNamespace(install_id=B, custody=SimpleNamespace(held_lists=self.held_lists)))
        mp.setattr(capabilities, "MESH_BUILD_ON", True)
        mp.setattr(machines_runtime, "wiring", lambda: wired)
        mp.setattr(mesh_peers, "REGISTRY", self.reg)
        mp.setattr(peer_links, "LINKS", StarLinks())
        mp.setattr(mesh, "snapshot", lambda: {"switch": "on", "links": [{"install_id": i, "standing": i != H, "on_demand": i == H} for i in REGISTRY_CAPS]})
        mp.setattr(gossip, "heard_now", lambda: self.cards)
        mp.setattr(mesh, "ensure", self.boom, raising=False)
        self.view = MemberView(Deps(look=self.look, clock=lambda: self.now[0]))
        mp.setattr(member_view, "_COPY_VIEW", self.view)
        mp.setattr(replicas, "_default_add", lambda: self.add)
        mp.setattr(replicas, "_default_has", lambda uid, iid: iid in self.held)
        self.mp = mp

    def boom(self, *_a: Any, **_k: Any) -> None:
        raise AssertionError("a copy run must never dial")

    def db(self) -> Any:
        return connect(db_path_for(self.state), create=False)

    def lst(self) -> RosterV2:
        rows = [RosterComputerV2(install_id=i, label=i[4:], fed_public_key=b64url(DeviceKey.from_seed(bytes([ORDER.index(i) + 3]) * 32).raw_pub), cert=CERT, mesh=i not in self.off,
                                 link_peers=i not in self.link_off, one_way=i in self.one_way) for i in ORDER if i not in self.removed]
        return RosterV2(generation=1, alpha=A, home=A, issued_at=1, computers=rows)

    def held_lists(self) -> List[Any]:
        if self.unreadable:
            raise OSError("unreadable")
        return [self.lst()]

    async def look(self, iid: str, uid: str, dial: bool) -> Any:
        self.looks.append((iid, dial))
        return self.answers.get(iid, (0, None))

    async def add(self, name: str, req: AddReplicaRequest) -> Dict[str, Any]:
        self.tries.append(req.machine)
        if req.machine in self.refuse:
            raise HTTPException(403, {"code": self.refuse[req.machine], "detail": "refused"})
        self.adds.append(req.machine)
        self.held.add(req.machine)
        return {"replica": {"folder_made": True}}

    async def carry(self, root: str, uid: str, peer: str) -> Dict[str, Any]:
        self.carries.append(peer)
        return {"sent": True}

    def base(self, *, star: bool = False) -> PlaceView:
        me = rule.MachineInput(B, "b", rich(B), True, True, True, True, 0)
        peers = [rule.MachineInput(S, "s", rich(S), True, False, False, False, None)] if star else []
        return PlaceView(me, peers, {S: [CAP_JOBS]} if star else {}, None)

    def sync(self, *, members: bool = True, star: bool = False) -> keep_sync.KeepSync:
        async def make(name: str, uid: str, peer: str) -> bool:
            return await replicas.ensure(name, uid, peer, store=self.store, add=self.add, has=lambda u, i: i in self.held)

        async def prewarm(*_a: Any) -> Dict[str, Any]:
            return {}

        return keep_sync.KeepSync(self.store, carry=self.carry, view_for=lambda r, u: self.base(star=star), gauge=lambda: {}, prewarm=prewarm,
                                  project_of=lambda uid: {"root": "/r/p", "uid": uid, "display_name": "P"}, digest_of=lambda r: "d1", head_of=lambda r: "c" * 40,
                                  clock=lambda: self.now[0], make_copy=make,
                                  members=functools.partial(member_view.for_copies, store=self.store, self_iid=B) if members else None)

    async def copies(self, *, star: bool = False) -> Dict[str, str]:
        view = await member_view.for_copies(self.base(star=star), "/r/p", UID, store=self.store, self_iid=B)
        return await replicas.ensure_all("P", UID, store=self.store, view=view, policy=policy_mod.get(self.store, UID), add=self.add,
                                         has=lambda u, i: i in self.held)

    def live_rows(self, iid: str, n: int) -> None:
        for k in range(n):
            self.store.create_job(JobRecord(id=f"job_{iid}_{k}", idem_key=f"k{iid}{k}", project_uid=UID, project_name="P", caller_session="s", request_json="{}",
                                            state=JobState.RUNNING, peer_install_id=iid, peer_label=iid, created_at=1.0, updated_at=1.0))


@pytest.fixture()
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return World(tmp_path, monkeypatch)


def test_switch_off_is_today(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)

    def no_read(*_a: Any) -> Any:
        raise AssertionError("read while the switch is off")

    monkeypatch.setattr(member_view, "_COPY_VIEW", MemberView(Deps(read=no_read, look=world.look)))
    view = world.base(star=True)
    assert asyncio.run(member_view.for_copies(view, "/r/p", UID, store=world.store, self_iid=B)) is view
    out = asyncio.run(world.copies(star=True))
    assert out == {S: "created"} and world.adds == [S] and world.looks == []
    sync = world.sync(star=True)
    policy_mod.record_auto_replica(world.store, UID, S)
    assert [r["outcome"] for r in asyncio.run(sync.tick())] == ["sent"] and world.carries == [S] and world.looks == []
    assert member_link.copy_refusal(G, "g") is None and world.reg.clients == [] and world.reg.connects == []


def test_copies_reach_c_and_g_only_and_never_dial(world: World) -> None:
    out = asyncio.run(world.copies(star=True))
    assert out == {S: "created", C: "present", G: "created"} and world.adds == [S, G]
    assert {i for i, _d in world.looks} == {C, G, J} and not any(dial for _i, dial in world.looks)
    assert world.reg.connects == [] and world.reg.clients == []


def test_a_member_holding_four_jobs_still_gets_its_copy(world: World) -> None:
    world.live_rows(G, 4)
    assert asyncio.run(world.copies())[G] == "created" and world.adds == [G]


def test_a_replica_homed_elsewhere_makes_no_copies(world: World) -> None:
    with closing(world.db()) as conn:
        conn.execute("UPDATE projects SET home_install_id = ? WHERE uid = ?", (C, UID))
    world.answers = {i: (200, {"snapshot": rich(i), "project": "ok"}) for i in (C, G, J)}
    view = world.base()
    assert asyncio.run(member_view.for_copies(view, "/r/p", UID, store=world.store, self_iid=B)) is view
    assert asyncio.run(world.copies()) == {} and world.adds == [] and world.looks == []


def test_keep_sync_copies_to_g_and_a_removed_g_gets_nothing_on_the_next_tick(world: World) -> None:
    policy_mod.record_auto_replica(world.store, UID, C)
    sync = world.sync()
    out = asyncio.run(sync.tick())
    assert ("copy_made", G) in [(r["outcome"], r["peer"]) for r in out] and sorted(world.carries) == [C, G] and world.adds == [G]
    world.removed.add(G)
    world.carries.clear()
    world.now[0] += 120
    sync.on_reconnect(C)
    asyncio.run(sync.tick())
    assert world.carries == [C] and world.adds == [G]


def test_a_receiver_that_refuses_the_copy_is_recorded_and_backed_off(world: World) -> None:
    world.refuse[G] = "pack_restricted"
    assert asyncio.run(world.copies())[G] == "pack_restricted"
    sync = world.sync()
    out = asyncio.run(sync.tick())
    assert [(r["outcome"], r["code"]) for r in out if r["peer"] == G] == [("copy_refused", "pack_restricted")]
    assert copy_run.get(UID)["refused"].get(G) == "pack_restricted"
    world.now[0] += 60
    assert [r for r in asyncio.run(sync.tick()) if r["peer"] == G] == [] and world.adds == []


def _replica_add_stubs(world: World, monkeypatch: pytest.MonkeyPatch, target: str) -> Any:
    async def no_call(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("reached a computer the guard refused")

    monkeypatch.setattr(project_replica_routes, "find_peer", lambda machine, members=False: SimpleNamespace(peer_install_id=target, label="g", key="g"))
    monkeypatch.setattr(project_replica_routes, "call_peer", no_call)
    monkeypatch.setattr(project_replica_routes.direction, "contained", lambda iid: False)
    monkeypatch.setattr(projects_service, "open_db_or_503", lambda _settings: world.db())
    return no_call


def test_the_copy_guard_refuses_a_computer_the_list_no_longer_allows(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    assert member_link.copy_refusal(C, "c") is None and member_link.copy_refusal(G, "g") is None
    world.one_way.add(G)
    assert member_link.copy_refusal(G, "g")[:2] == (409, "computer_one_way")
    world.one_way.discard(G)
    for change, code in ((lambda: world.removed.add(G), "member_not_listed"), (lambda: (world.removed.clear(), world.off.add(G)), "member_not_mesh"),
                         (lambda: (world.off.clear(), world.link_off.add(G)), "member_link_off"),
                         (lambda: (world.link_off.discard(G), world.__setattr__("unreadable", True)), "member_list_unreadable")):
        change()
        assert member_link.copy_refusal(G, "g")[:2] == (502, code)
    world.unreadable = False
    monkeypatch.setattr(peer_links, "LINKS", SimpleNamespace(client=lambda iid: object()))
    world.removed.add(G)
    assert member_link.copy_refusal(G, "g") is None, "a live star client keeps the star path as it is"
    monkeypatch.setattr(peer_links, "LINKS", StarLinks())
    no_call = _replica_add_stubs(world, monkeypatch, G)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(project_replica_routes.add_project_replica("P", AddReplicaRequest(machine=G, transport="carried")))
    assert caught.value.status_code == 502 and caught.value.detail["code"] == "member_not_listed"
    monkeypatch.setattr(member_link, "client_for", no_call)
    sent = asyncio.run(project_transport_routes.carry_to({"root": "/r/p", "uid": UID}, G, "g", True, mesh=True))
    assert sent == {"machine": "g", "sent": False, "error": "member_not_listed"}


def test_each_reason_has_its_own_code_and_the_allowed_set_is_exactly_ids_in(world: World) -> None:
    lst = world.lst()
    allowed = {i for i in ORDER if member_link.copy_refusal(i, i) is None}
    assert allowed == set(member_reach.ids_in(lst)) and allowed
    assert member_link.copy_refusal(B, "b")[:2] == (502, "machine_unreachable") and member_link.copy_refusal(A, "a")[:2] == (502, "machine_unreachable")
    world.link_off.add(B)
    refusal = member_link.copy_refusal(C, "c")
    assert refusal[:2] == (502, "own_link_off") and "Error" not in refusal[2] and "Traceback" not in refusal[2]
    world.link_off.discard(B)
    world.unreadable = True
    assert member_link.copy_refusal(C, "c")[:2] == (502, "member_list_unreadable")


def test_a_new_copy_with_an_unreadable_list_is_refused_at_once(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    world.unreadable = True
    _replica_add_stubs(world, monkeypatch, G)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(project_replica_routes.add_project_replica("P", AddReplicaRequest(machine=G, transport="carried")))
    assert caught.value.status_code == 502 and caught.value.detail["code"] == "member_list_unreadable"


def test_q5_a_keep_sync_commit_send_never_rides_a_pair_a_job_opened_on_demand(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    touched: List[str] = []
    monkeypatch.setattr(mesh, "on_demand", lambda iid: iid == H)
    monkeypatch.setattr(mesh, "touch", touched.append)
    project = {"root": "/r/p", "uid": UID}
    sent = asyncio.run(project_transport_routes.carry_to(project, H, "h", False, mesh=True, copy_send=True))
    assert sent == {"machine": "h", "sent": False, "error": "member_on_demand_only"} and world.reg.clients == [] and touched == []
    asyncio.run(project_transport_routes.carry_to(project, H, "h", False, mesh=True))
    assert world.reg.clients == [H], "a job's own carry (no copy_send) still looks the client up"


def test_n2_a_copy_send_is_never_refused_as_on_demand_while_a_star_client_is_live(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mesh, "on_demand", lambda iid: iid == H)
    monkeypatch.setattr(peer_links, "LINKS", SimpleNamespace(client=lambda iid: object(), capabilities=lambda iid: []))
    sent = asyncio.run(project_transport_routes.carry_to({"root": "/r/p", "uid": UID}, H, "h", False, mesh=True, copy_send=True))
    assert sent.get("error") == "runs_older_carnivore", sent


def test_n4_a_one_way_target_is_named_before_this_computers_own_switch(world: World) -> None:
    world.link_off.add(B)
    refusal = member_link.copy_refusal(D, "d")
    assert refusal is not None and refusal[:2] == (409, "computer_one_way")
    assert member_link.copy_refusal(G, "g")[:2] == (502, "own_link_off")


def test_q6_a_read_error_cannot_abort_the_tick_and_the_star_copy_is_still_sent(world: World) -> None:
    def bad_read(*_a: Any) -> Any:
        raise sqlite3.OperationalError("database is locked")

    world.mp.setattr(member_view, "_COPY_VIEW", MemberView(Deps(read=bad_read, look=world.look)))
    policy_mod.record_auto_replica(world.store, UID, S)
    out = asyncio.run(world.sync(star=True).tick())
    assert [r["outcome"] for r in out] == ["sent"] and world.carries == [S]


class Refusing:

    def __init__(self, world: World, error: str, peers: Set[str]) -> None:
        self.world, self.error, self.peers, self.calls = world, error, peers, []

    async def __call__(self, root: str, uid: str, peer: str) -> Dict[str, Any]:
        self.calls.append(peer)
        return {"sent": False, "error": self.error} if peer in self.peers else {"sent": True}


def _fails(world: World, peer: str) -> int:
    state = world.store.sync_get(UID, peer)
    return state["fails"] if state else 0


def test_k1_a_passing_refusal_earns_no_back_off_and_the_next_tick_tries_again(world: World) -> None:
    policy_mod.record_auto_replica(world.store, UID, C)
    policy_mod.record_auto_replica(world.store, UID, S)
    refuse = Refusing(world, "mesh_power_refused", {C})
    world.refuse[G] = "mesh_power_refused"
    sync = world.sync(star=True)
    sync._carry = refuse
    sync.on_reconnect(C)
    asyncio.run(sync.tick())
    assert refuse.calls.count(C) == 1 and _fails(world, C) == 0
    world.now[0] += 60
    asyncio.run(sync.tick())
    assert refuse.calls.count(C) == 2, "tried again at the next tick"
    world.now[0] += 60
    asyncio.run(sync.tick())
    assert world.tries.count(G) == 3 and _fails(world, G) == 0
    star = Refusing(world, "machine_unreachable", {S})
    sync._carry = star
    sync.on_reconnect(S)
    asyncio.run(sync.tick())
    world.now[0] += 60
    asyncio.run(sync.tick())
    assert star.calls.count(S) == 1 and _fails(world, S) == 1, "a star refusal backs off as today"


def test_k1_negative_control_a_receiver_that_keeps_refusing_is_stopped_at_the_look(world: World) -> None:
    world.answers[C] = (403, {"detail": {"code": "mesh_power_refused"}})
    world.answers[G] = (403, {"detail": {"code": "mesh_power_refused"}})
    policy_mod.record_auto_replica(world.store, UID, C)
    refuse = Refusing(world, "mesh_power_refused", {C, G})
    sync = world.sync()
    sync._carry = refuse
    for _ in range(3):
        world.now[0] += 60
        asyncio.run(sync.tick())
    assert refuse.calls == [] and world.tries == [] and _fails(world, C) == 0 and _fails(world, G) == 0


@pytest.mark.parametrize("hold", [True, False])
def test_n1_a_member_that_refuses_every_send_after_its_look_is_held_off_and_a_success_clears_it(world: World, monkeypatch: pytest.MonkeyPatch, hold: bool) -> None:
    if not hold:
        monkeypatch.setattr(keep_sync, "REMOTE_PASSING", set())
    policy_mod.record_auto_replica(world.store, UID, C)
    refuse = Refusing(world, "mesh_power_refused", {C})
    sync = world.sync(star=True)
    sync._carry = refuse
    sync.on_reconnect(C)
    for _ in range(60):
        asyncio.run(sync.tick())
        world.now[0] += 60
    assert refuse.calls.count(C) == (7 if hold else 60) and _fails(world, C) == 0
    if hold:
        refuse.peers.clear()
        world.now[0] += keep_sync.BACKOFF_BASE_S
        out = asyncio.run(sync.tick())
        assert [r["outcome"] for r in out] == ["sent"] and not sync._passing_hold and _fails(world, C) == 0


def test_e2_a_reconnect_ends_the_passing_hold_of_that_peer_alone(world: World) -> None:
    policy_mod.record_auto_replica(world.store, UID, C)
    refuse = Refusing(world, "mesh_power_refused", {C})
    sync = world.sync(star=True)
    sync._carry = refuse
    sync.on_reconnect(C)
    for _ in range(3):
        asyncio.run(sync.tick())
        world.now[0] += 60
    assert any(k[1] == C for k in sync._passing_hold)
    sync._passing_hold[(UID, G)] = (1, world.now[0] + 9999.0)
    before = refuse.calls.count(C)
    sync.on_reconnect(C)
    assert not any(k[1] == C for k in sync._passing_hold) and (UID, G) in sync._passing_hold
    asyncio.run(sync.tick())
    assert refuse.calls.count(C) == before + 1


def test_k2_a_member_with_no_status_card_is_named_in_the_copy_run_and_gets_no_copy(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    world.cards.pop(G)

    async def seed(*_a: Any) -> List[str]:
        return []

    monkeypatch.setattr(pack_jobs_routes.ssh_owner, "seed_targets", seed)
    monkeypatch.setattr(pack_jobs_routes.place, "live_view", lambda r, u: world.base())
    monkeypatch.setattr(pack_jobs_routes.home, "notify_changed", lambda: None)
    asyncio.run(pack_jobs_routes._ensure(SimpleNamespace(store=world.store, install_id=B), "P", UID, "/r/p"))
    refused = copy_run.get(UID)["refused"]
    assert refused[G] == "no_status_card" and refused[F] == "not_linked" and refused[H] == "on_demand_only" and refused[I] == "older_app"
    assert world.adds == [] and G not in world.held
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    assert asyncio.run(member_view.for_copies(world.base(), "/r/p", UID, store=world.store, self_iid=B)).copy_skips == {}


def test_the_real_read_facts_reads_the_members_counterparts_links_and_held_jobs(world: World) -> None:
    world.live_rows(C, 1)
    facts = member_view.read_facts("/r/p", UID, B, world.store)
    assert facts.members == [C, G, F, H, I, J, K] and facts.counterparts == {C} and facts.home == B
    assert facts.star == {A, S} and facts.linked == {C, G, H, I, J, K} and facts.free_on_demand == mesh.MAX_ON_DEMAND - 1
    assert facts.held == {C: 1} and facts.on_demand == {H} and facts.self_one_way is False
    assert A not in facts.members and D not in facts.members and E not in facts.members


def test_the_copy_run_route_builds_its_view_through_for_copies(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    async def seed(*_a: Any) -> List[str]:
        return []

    monkeypatch.setattr(pack_jobs_routes.ssh_owner, "seed_targets", seed)
    monkeypatch.setattr(pack_jobs_routes.place, "live_view", lambda r, u: world.base(star=True))
    monkeypatch.setattr(pack_jobs_routes.home, "notify_changed", lambda: None)
    eng = SimpleNamespace(store=world.store, install_id=B)
    asyncio.run(pack_jobs_routes._ensure(eng, "P", UID, "/r/p"))
    assert world.adds == [S, G] and copy_run.get(UID)["error"] is None and copy_run.get(UID)["refused"] == {F: "not_linked", H: "on_demand_only", I: "older_app", K: "no_status_card"} and world.reg.connects == []
    world.adds.clear()
    world.held.discard(S)
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    asyncio.run(pack_jobs_routes._ensure(eng, "P", UID, "/r/p"))
    assert world.adds == [S]
