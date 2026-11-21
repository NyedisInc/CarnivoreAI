
from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

import structlog

from src.core.pack.jobs import copy_run, gitio, policy as policy_mod, snapshot
from src.core.pack.jobs.place import PlaceView, drop_reason
from src.core.pack.jobs.prewarm import CAP_PREWARM
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import DepDir
from src.core.pack.machines import capabilities

log = structlog.get_logger(__name__)

EVERY_S = 60.0
RESEND_AFTER_S = 15 * 60.0
BACKOFF_BASE_S = 15 * 60.0
BACKOFF_CAP_S = 4 * 3600.0
DIGEST_KEEP_S = 60.0
PREWARM_HELD = "beast mode is off: the first approved job sets the dependencies up"

CarryFn = Callable[[str, str, str], Awaitable[Optional[Dict[str, Any]]]]
PrewarmFn = Callable[[str, str, str, List[DepDir], Optional[List[str]]], Awaitable[Dict[str, Any]]]
_SENDING: Set[str] = set()


def sending(project_uid: str) -> bool:
    return project_uid in _SENDING


def refs_digest(root: str) -> Optional[str]:
    cp = gitio.run(["for-each-ref", "--format=%(refname) %(objectname)", "refs/heads", "refs/tags"], cwd=root, check=False)
    return hashlib.sha256(cp.stdout).hexdigest() if cp.returncode == 0 else None


def head_commit(root: str) -> Optional[str]:
    cp = gitio.run(["rev-parse", "--verify", "-q", "HEAD"], cwd=root, check=False)
    return gitio.out(cp) if cp.returncode == 0 else None


def backoff_s(fails: int) -> float:
    return min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2 ** max(0, fails - 1)) if fails > 0 else 0.0


def _on_battery(snapshot_doc: Optional[Dict[str, Any]]) -> bool:
    battery = (snapshot_doc or {}).get("battery")
    return isinstance(battery, dict) and battery.get("on_battery") is True


def _pegged(snapshot_doc: Optional[Dict[str, Any]]) -> bool:
    gauge = (snapshot_doc or {}).get("pressure")
    return isinstance(gauge, dict) and gauge.get("pegged") is True


class KeepSync:

    def __init__(self, store: JobStore, *, carry: CarryFn, view_for: Callable[[str, str], PlaceView], gauge: Callable[[], Optional[Dict[str, Any]]],
                 prewarm: PrewarmFn, project_of: Callable[[str], Optional[Dict[str, Any]]],
                 live_jobs: Optional[Callable[[str, str], bool]] = None, copy_running: Callable[[str], bool] = lambda uid: copy_run.get(uid)["running"],
                 digest_of: Callable[[str], Optional[str]] = refs_digest, head_of: Callable[[str], Optional[str]] = head_commit,
                 deps_of: Callable[[str], List[DepDir]] = snapshot.dep_dirs_of, clock: Callable[[], float] = time.time,
                 may_prewarm: Callable[[], bool] = lambda: False) -> None:
        self.store, self._carry, self._view_for, self._gauge, self._prewarm = store, carry, view_for, gauge, prewarm
        self._project_of, self._copy_running, self._digest_of, self._head_of, self._deps_of = project_of, copy_running, digest_of, head_of, deps_of
        self._live_jobs = live_jobs or self._store_live_jobs
        self._clock = clock
        self._may_prewarm = may_prewarm
        self._held_reason: Dict[Any, str] = {}
        self._reconnected: Set[str] = set()
        self._digests: Dict[str, "tuple[float, Optional[str]]"] = {}
        self._wake = asyncio.Event()
        self._lock = asyncio.Lock()

    def _store_live_jobs(self, project_uid: str, peer: str) -> bool:
        return any(j.peer_install_id == peer for j in self.store.list_jobs(project_uid=project_uid, live_only=True, limit=200))

    def on_reconnect(self, peer: str) -> None:
        self._reconnected.add(peer)
        self._wake.set()

    async def _digest(self, uid: str, root: str) -> Optional[str]:
        now = self._clock()
        held = self._digests.get(uid)
        if held is not None and now - held[0] < DIGEST_KEEP_S:
            return held[1]
        digest = await asyncio.to_thread(self._digest_of, root)
        self._digests[uid] = (now, digest)
        return digest

    def _skip(self, uid: str, peer: Any, view: PlaceView, policy: policy_mod.Policy, state: Optional[Dict[str, Any]], back: bool) -> Optional[str]:
        if not peer.usable:
            return "not connected"
        why = drop_reason(peer, policy, view)
        if why:
            return why
        if self._copy_running(uid):
            return "the copy run is working on this project"
        if _on_battery(self._gauge()) or _on_battery(peer.snapshot):
            return "a computer is on battery"
        if _pegged(peer.snapshot):
            return "the other computer is pegged"
        if self._live_jobs(uid, peer.install_id):
            return "a live job of this project runs there"
        if state and state["fails"] and self._clock() < state["last_try"] + backoff_s(state["fails"]):
            return "backing off after a failure"
        return None

    def _due(self, state: Optional[Dict[str, Any]], digest: Optional[str], back: bool) -> bool:
        if back or state is None or not state["last_ok"]:
            return True
        return digest is not None and digest != state["refs_digest"] and self._clock() - state["last_ok"] >= RESEND_AFTER_S

    async def _send(self, uid: str, root: str, peer: Any, view: PlaceView, policy: policy_mod.Policy, state: Optional[Dict[str, Any]],
                    digest: Optional[str]) -> Dict[str, Any]:
        now = self._clock()
        row: Dict[str, Any] = {"project_uid": uid, "peer": peer.install_id}
        if self._copy_running(uid):
            return {**row, "outcome": "skipped", "error": "the copy run is working on this project"}
        _SENDING.add(uid)
        try:
            result = await self._carry(root, uid, peer.install_id) or {}
        finally:
            _SENDING.discard(uid)
        sent = bool(result.get("sent"))
        if not sent and result.get("reason") != "nothing_new":
            fails = (state["fails"] if state else 0) + 1
            await asyncio.to_thread(self.store.sync_put, uid, peer.install_id, fails=fails, last_try=now)
            log.info("pack_keep_sync_failed", project_uid=uid, peer=peer.install_id, fails=fails, error=result.get("error") or result.get("reason"))
            return {**row, "outcome": "failed", "error": result.get("error") or result.get("reason")}
        await asyncio.to_thread(self.store.sync_put, uid, peer.install_id, refs_digest=digest or "", last_ok=now, last_try=now, fails=0)
        row["outcome"] = "sent" if sent else "current"
        warmed = state["warm_commit"] if state else ""
        if sent and capabilities.has(view.caps.get(peer.install_id), CAP_PREWARM):
            head = await asyncio.to_thread(self._head_of, root)
            if head and head != warmed and not self._may_prewarm():
                row["prewarm"] = {"ok": False, "reason": PREWARM_HELD}
                if self._held_reason.get((uid, peer.install_id)) != PREWARM_HELD:
                    self._held_reason[(uid, peer.install_id)] = PREWARM_HELD
                    log.info("pack_keep_sync_prewarm_held", project_uid=uid, peer=peer.install_id, reason=PREWARM_HELD)
            elif head and head != warmed:
                self._held_reason.pop((uid, peer.install_id), None)
                deps = await asyncio.to_thread(self._deps_of, root)
                answer = await self._prewarm(peer.install_id, uid, head, deps, policy.setup)
                row["prewarm"] = answer
                if answer.get("ok"):
                    await asyncio.to_thread(self.store.sync_put, uid, peer.install_id, warm_commit=head)
        return row

    async def tick(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        async with self._lock:
            for uid in await asyncio.to_thread(self.store.marked_projects):
                policy = await asyncio.to_thread(policy_mod.get, self.store, uid)
                copies = await asyncio.to_thread(policy_mod.auto_replicas, self.store, uid) if policy.auto_delegate else []
                project = await asyncio.to_thread(self._project_of, uid) if copies else None
                if not project or not project.get("root"):
                    continue
                root = project["root"]
                view = await asyncio.to_thread(self._view_for, root, uid)
                digest: Optional[str] = None
                for install_id in copies:
                    peer = next((p for p in view.peers if p.install_id == install_id), None)
                    state = await asyncio.to_thread(self.store.sync_get, uid, install_id)
                    back = install_id in self._reconnected
                    if peer is None:
                        self._reconnected.discard(install_id)
                        continue
                    if await asyncio.to_thread(self._skip, uid, peer, view, policy, state, back):
                        continue
                    digest = digest or await self._digest(uid, root)
                    if not self._due(state, digest, back):
                        continue
                    self._reconnected.discard(install_id)
                    out.append(await self._send(uid, root, peer, view, policy, state, digest))
        return out

    async def run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), EVERY_S)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            try:
                await self.tick()
            except Exception as exc:  # noqa: BLE001
                log.warning("pack_keep_sync_tick_failed", error=type(exc).__name__)
