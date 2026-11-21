
from __future__ import annotations

import asyncio
from contextlib import closing
from typing import Any, Dict, List

import pytest

pytest.importorskip("fastapi")

from test_pack_jobs_two_machines import git, snap, world  # noqa: E402,F401

from src.api import federation_pack_install_routes as install_routes  # noqa: E402
from src.api import federation_pack_jobs_routes as jobs_routes  # noqa: E402
from src.core.pack.jobs import host_admit, keep_sync, policy as policy_mod  # noqa: E402
from src.core.pack.jobs.engine import Engine  # noqa: E402
from src.core.pack.jobs.install import CAP_INSTALL, Installer  # noqa: E402
from src.core.pack.jobs.place import PlaceView  # noqa: E402
from src.core.pack.jobs.prewarm import CAP_PREWARM  # noqa: E402
from src.core.pack.jobs.target import PeerTarget  # noqa: E402
from src.core.pack.jobs.types import CAP_JOBS, CAP_NEEDS, JobRequest, JobState  # noqa: E402
from src.core.pack.machines.restrictions import Restrictions  # noqa: E402
from src.core.pack.placement import rule  # noqa: E402
from src.core.pack.transport import sync  # noqa: E402

CAPS = [CAP_JOBS, CAP_NEEDS, CAP_INSTALL, CAP_PREWARM]


def rich(load1: float, *, labels: List[str] = (), tools: Dict[str, bool] = None, brew: bool = True, pegged: bool = False) -> Dict[str, Any]:
    doc = snap(load1)
    doc["can"] = {"v": 1, "brew": brew, "tools": dict(tools or {}), "labels": list(labels)}
    doc["pressure"] = {"v": 1, "pegged": pegged}
    doc["restrictions"] = {"may_host_agents": True, "may_install_tools": True}
    return doc


def job(w: Any, command: str, **kw: Any) -> JobRequest:
    return JobRequest(command=command, folder=str(w.a.root), kind="suite", caller_session="ses_test", time_cap_s=60, **kw)


def build(w: Any, a_snap: Dict[str, Any], b_snap: Dict[str, Any]) -> Engine:
    async def fast(seconds: float) -> None:
        await asyncio.sleep(min(seconds, 0.1))

    async def no_carry(*_a: Any, **_k: Any) -> None:
        pass

    me = rule.MachineInput("iid-a", "a", a_snap, True, True, True, True, 0)
    other = rule.MachineInput("iid-b", "b", b_snap, True, False, False, True, None)
    engine = Engine(state_dir=w.a.state, jobs_root=w.a.jobs, install_id="iid-a", open_db=w.a.conn,
                    view_for=lambda root, uid: PlaceView(me, [other], {"iid-b": CAPS}, "iid-a", None),
                    target_for=lambda iid: PeerTarget(iid, "b", w.link(w.a, w.b)), sleep=fast, restrictions=lambda: w.a.restrictions,
                    carry_commits=no_carry)
    policy_mod.set_auto(engine.store, w.uid, True)
    return engine


def test_a_label_only_b_has_sends_the_job_to_b(world, monkeypatch) -> None:
    w = world
    b_snap = rich(1.0, labels=["rtx 4090"])
    monkeypatch.setattr(host_admit, "own_snapshot", lambda: b_snap)
    engine = build(w, rich(1.0), b_snap)

    async def flow():
        rec = await engine.submit(job(w, "echo hi", needs=["label:rtx 4090"]))
        return rec, await engine.wait(rec.id, 90)

    rec, done = asyncio.run(flow())
    assert rec.peer_install_id == "iid-b", rec
    assert done.state == JobState.DONE and "hi" in (done.output_tail or ""), done


def test_a_need_nobody_has_is_refused_with_the_plain_reason(world) -> None:
    w = world
    rec = asyncio.run(build(w, rich(1.0), rich(1.0)).propose(job(w, "echo hi", needs=["label:no such box"])))
    assert rec.state == JobState.REFUSED and rec.error_code == "requirement_unmet", rec
    assert "no such box" in (rec.reason or "") and not (w.a.jobs / "repos").exists()


def test_a_missing_tool_is_installed_after_the_approval_and_then_the_job_runs(world, monkeypatch) -> None:
    w = world
    b_snap = rich(1.0, tools={"ffmpeg": False})
    monkeypatch.setattr(host_admit, "own_snapshot", lambda: b_snap)
    ran: List[List[str]] = []

    def fake_brew(argv: List[str], env: Dict[str, str], log: Any, timeout: float) -> Any:
        ran.append(argv)
        return 0, ""

    installer = Installer(w.host.store, w.b.jobs, brew=lambda: "/fake/brew", restrictions=lambda: Restrictions(), present=lambda _tool: False, run_proc=fake_brew,
                          owns_job=lambda job_id, caller: host_admit.HOLDS.owner(job_id) == caller)
    w.b.app.state.pack_jobs_installer = installer
    w.b.app.include_router(install_routes.router, prefix="/api/v1")
    engine = build(w, rich(1.0), b_snap)

    async def flow():
        waiting = await engine.propose(job(w, "echo ok", needs=["ffmpeg"]))
        assert waiting.state == JobState.WAITING_APPROVAL and not ran, "nothing installs before the owner approves"
        w.b.app.dependency_overrides[install_routes._require_replica] = w.b.app.dependency_overrides[jobs_routes._require_replica]
        await engine.proceed(waiting.id)
        return waiting, await engine.wait(waiting.id, 90)

    waiting, done = asyncio.run(flow())
    assert '"install": ["ffmpeg"]' in waiting.request_json
    assert ran == [["/fake/brew", "install", "--formula", "ffmpeg"]]
    assert done.state == JobState.DONE and "ok" in (done.output_tail or ""), done


def test_a_pegged_a_with_room_on_b_sends_the_job_to_b(world, monkeypatch) -> None:
    w = world
    monkeypatch.setattr(host_admit, "own_snapshot", lambda: rich(1.0))
    engine = build(w, rich(0.5, pegged=True), rich(1.0))
    rec = asyncio.run(engine.propose(job(w, "echo hi")))
    assert rec.state == JobState.WAITING_APPROVAL and rec.peer_install_id == "iid-b", rec


@pytest.mark.parametrize("beast", [True, False])
def test_keep_in_sync_moves_a_new_commit_to_b_and_asks_it_to_warm_only_with_beast(world, beast: bool) -> None:
    w = world
    (w.a.root / "g.txt").write_text("two\n")
    git(w.a.root, "add", "g.txt")
    git(w.a.root, "commit", "-q", "-m", "second")
    head = git(w.a.root, "rev-parse", "HEAD")
    store = w.host.store.__class__(w.a.state)
    policy_mod.set_auto(store, w.uid, True)
    store.auto_replica_add(w.uid, "iid-b")
    warmed: List[Any] = []

    async def carry(root: str, uid: str, peer: str) -> Dict[str, Any]:
        return await sync.carry_bundle(repo=root, project_uid=uid, peer_install_id=peer, request=w.link(w.a, w.b), open_db=w.a.conn,
                                       outbox=str(w.a.state / "pack" / "outbox"), air_gap=True)

    async def prewarm(peer: str, uid: str, commit: str, deps: Any, setup: Any) -> Dict[str, Any]:
        warmed.append((peer, commit))
        return {"ok": True}

    me = rule.MachineInput("iid-a", "a", rich(1.0), True, True, True, True, 0)
    other = rule.MachineInput("iid-b", "b", rich(1.0), True, False, False, True, None)
    loop = keep_sync.KeepSync(store, carry=carry, view_for=lambda root, uid: PlaceView(me, [other], {"iid-b": CAPS}, "iid-a", None),
                              gauge=lambda: rich(1.0), prewarm=prewarm, project_of=lambda uid: {"root": str(w.a.root), "uid": uid},
                              copy_running=lambda uid: False, may_prewarm=lambda: beast)
    rows = asyncio.run(loop.tick())
    assert [(r["peer"], r["outcome"]) for r in rows] == [("iid-b", "sent")], rows
    assert warmed == ([("iid-b", head)] if beast else [])
    assert git(w.b.root, "cat-file", "-t", head) == "commit"
    assert asyncio.run(loop.tick()) == [], "nothing changed, nothing is sent"


def _light_view(own_load: float, peer_load: float) -> PlaceView:
    me = rule.MachineInput("me", "mac", rich(own_load), is_self=True, is_home=True)
    peer = rule.MachineInput("tower", "tower", rich(peer_load))
    return PlaceView(me, [peer], {"tower": CAPS}, "me")


def test_light_work_leaves_a_computer_past_its_reserve_for_a_peer_with_room() -> None:
    from src.core.pack.jobs.place import place
    from src.core.pack.placement.workload import Workload

    pol = policy_mod.Policy("p1", auto_delegate=True)
    light = Workload()
    assert place(light, "p1", pol, _light_view(2.0, 1.0)).decision == "here"
    moved = place(light, "p1", pol, _light_view(9.5, 1.0))
    assert (moved.decision, moved.peer_install_id) == ("remote", "tower")
    assert place(light, "p1", pol, _light_view(9.5, 9.5)).decision == "here"
