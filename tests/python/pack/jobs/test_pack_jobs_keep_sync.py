
from __future__ import annotations

import asyncio
import functools
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.core.pack.jobs import keep_sync
from src.core.pack.jobs.place import PlaceView
from src.core.pack.jobs.prewarm import CAP_PREWARM
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import CAP_JOBS, DepDir, JobRecord, JobState
from src.core.pack.placement import rule

UID = "uid12345abcd"
PEER = "iid-b"


def arun(fn):
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


class Rig:

    def __init__(self, tmp: Path) -> None:
        self.store = JobStore(tmp)
        self.store.policy_upsert(UID, auto_delegate=1)
        self.store.auto_replica_add(UID, PEER)
        self.now = 10_000.0
        self.digest, self.head = "d1", "c" * 40
        self.sent: List[str] = []
        self.warmed: List[str] = []
        self.carry_result: Dict[str, Any] = {"sent": True, "refs": 1}
        self.copy_running = False
        self.beast = True
        self.own: Dict[str, Any] = {"battery": {"on_battery": False}, "pressure": {"pegged": True}}
        self.peer_snapshot: Dict[str, Any] = {"battery": {"on_battery": False}, "pressure": {"pegged": False}}
        self.usable = True
        self.caps = [CAP_JOBS, CAP_PREWARM]
        self.reads = 0
        self.sync = keep_sync.KeepSync(self.store, carry=self._carry, view_for=self._view, gauge=lambda: self.own, prewarm=self._prewarm,
                                       project_of=lambda uid: {"root": "/p", "uid": uid}, copy_running=lambda uid: self.copy_running,
                                       digest_of=self._digest, head_of=lambda root: self.head, deps_of=lambda root: [DepDir("n", "npm", {"l": "1"}, None)],
                                       clock=lambda: self.now, may_prewarm=lambda: self.beast)

    async def _carry(self, root: str, uid: str, peer: str):
        self.sent.append(peer)
        return self.carry_result

    async def _prewarm(self, peer: str, uid: str, commit: str, deps: Any, setup: Any):
        self.warmed.append(commit)
        return {"ok": True}

    def _digest(self, root: str) -> str:
        self.reads += 1
        return self.digest

    def _view(self, root: str, uid: str) -> PlaceView:
        peer = rule.MachineInput(PEER, "tower", self.peer_snapshot, usable=self.usable, has_project=True)
        return PlaceView(rule.MachineInput("iid-a", "home", None, is_self=True), [peer], {PEER: self.caps})

    def add_live_job(self) -> None:
        self.store.create_job(JobRecord(id="job_0123456789ab", project_uid=UID, state=JobState.RUNNING, peer_install_id=PEER, created_at=1, updated_at=1))


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


@arun
async def test_due_only_on_a_digest_change_after_fifteen_minutes(rig: Rig) -> None:
    first = await rig.sync.tick()
    assert [r["outcome"] for r in first] == ["sent"] and rig.warmed == [rig.head]
    rig.now += 16 * 60
    assert await rig.sync.tick() == []
    rig.digest, rig.now = "d2", rig.now + 60
    rig.sync._digests.clear()
    rig.store.sync_put(UID, PEER, last_ok=rig.now - 5 * 60)
    assert await rig.sync.tick() == []
    rig.now += 11 * 60
    rig.sync._digests.clear()
    assert [r["outcome"] for r in await rig.sync.tick()] == ["sent"] and rig.sent == [PEER, PEER]
    assert rig.store.sync_get(UID, PEER)["refs_digest"] == "d2"


@arun
async def test_reconnect_makes_it_due_and_nothing_new_warms_nothing(rig: Rig) -> None:
    await rig.sync.tick()
    rig.warmed.clear()
    rig.carry_result = {"sent": False, "reason": "nothing_new"}
    rig.now += 60
    rig.sync.on_reconnect(PEER)
    out = await rig.sync.tick()
    assert [r["outcome"] for r in out] == ["current"] and rig.warmed == []
    assert await rig.sync.tick() == []


@arun
async def test_prewarm_needs_the_capability_and_a_moved_tip(rig: Rig) -> None:
    rig.caps = [CAP_JOBS]
    await rig.sync.tick()
    assert rig.sent == [PEER] and rig.warmed == []
    rig.caps = [CAP_JOBS, CAP_PREWARM]
    rig.store.sync_put(UID, PEER, warm_commit=rig.head)
    rig.sync.on_reconnect(PEER)
    await rig.sync.tick()
    assert rig.warmed == []


@arun
@pytest.mark.parametrize("what", ["copy_run", "own_battery", "peer_battery", "peer_pegged", "live_job", "offline", "never_use", "no_takes_work"])
async def test_every_skip_sends_nothing(rig: Rig, what: str) -> None:
    if what == "copy_run":
        rig.copy_running = True
    elif what == "own_battery":
        rig.own["battery"] = {"on_battery": True}
    elif what == "peer_battery":
        rig.peer_snapshot["battery"] = {"on_battery": True}
    elif what == "peer_pegged":
        rig.peer_snapshot["pressure"] = {"pegged": True}
    elif what == "live_job":
        rig.add_live_job()
    elif what == "offline":
        rig.usable = False
    elif what == "never_use":
        rig.store.policy_upsert(UID, never_use_json='["tower"]')
    else:
        rig.peer_snapshot["restrictions"] = {"may_host_agents": False}
    rig.sync.on_reconnect(PEER)
    assert await rig.sync.tick() == [] and rig.sent == []


@arun
async def test_this_computer_pegged_does_not_skip(rig: Rig) -> None:
    assert rig.own["pressure"]["pegged"] is True
    assert [r["outcome"] for r in await rig.sync.tick()] == ["sent"]


@arun
async def test_backoff_doubles_and_caps(rig: Rig) -> None:
    assert [keep_sync.backoff_s(n) for n in (0, 1, 2, 3, 4, 5, 6, 9)] == [0.0, 900.0, 1800.0, 3600.0, 7200.0, 14400.0, 14400.0, 14400.0]
    rig.carry_result = {"sent": False, "error": "machine_unreachable"}
    assert [r["outcome"] for r in await rig.sync.tick()] == ["failed"]
    assert rig.store.sync_get(UID, PEER)["fails"] == 1
    rig.now += 899
    assert await rig.sync.tick() == []
    rig.now += 2
    assert [r["outcome"] for r in await rig.sync.tick()] == ["failed"] and rig.store.sync_get(UID, PEER)["fails"] == 2
    rig.now += 1799
    assert await rig.sync.tick() == []
    rig.sync.on_reconnect(PEER)
    assert await rig.sync.tick() == []
    rig.now += 2
    assert [r["outcome"] for r in await rig.sync.tick()] == ["failed"]


@arun
async def test_unmarked_project_reads_nothing_and_the_digest_is_cached(rig: Rig) -> None:
    rig.store.policy_upsert(UID, auto_delegate=0)
    assert await rig.sync.tick() == [] and rig.reads == 0
    rig.store.policy_upsert(UID, auto_delegate=1)
    await rig.sync.tick()
    rig.sync.on_reconnect(PEER)
    await rig.sync.tick()
    assert rig.reads == 1


@pytest.mark.asyncio
async def test_prewarm_is_held_while_a_delegate_job_would_need_a_card(rig: Rig) -> None:
    rig.beast = False
    out = await rig.sync.tick()
    assert [r["outcome"] for r in out] == ["sent"] and rig.warmed == []
    assert out[0]["prewarm"] == {"ok": False, "reason": keep_sync.PREWARM_HELD}
    assert not rig.store.sync_get(UID, PEER)["warm_commit"]
    rig.beast = True
    rig.sync.on_reconnect(PEER)
    rig.carry_result = {"sent": True, "refs": 2}
    await rig.sync.tick()
    assert rig.warmed == [rig.head]


def test_the_default_seam_never_asks_for_a_warm_up(rig: Rig) -> None:
    bare = keep_sync.KeepSync(rig.store, carry=rig._carry, view_for=rig._view, gauge=lambda: {}, prewarm=rig._prewarm, project_of=lambda u: None)
    assert bare._may_prewarm() is False
