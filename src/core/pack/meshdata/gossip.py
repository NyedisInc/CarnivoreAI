
from __future__ import annotations

import asyncio
import random
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog

from src.core.computers import direction
from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.pack.machines import capabilities, exchange
from src.core.pack.machines.roster_v2 import RosterV2
from src.core.pack.machines.settings_sign import Signing
from src.core.pack.meshdata import hlc, status, wire, withhold
from src.core.pack.meshdata.store import FILENAME, RecordStore

log = structlog.get_logger(__name__)

SYNC_PATH = "/federation/pack/mesh/sync"
DEBOUNCE_SECONDS = 2.0
PERIODIC_SECONDS = 600.0
JITTER_FRACTION = 0.2
MAX_CONCURRENT_PEERS = 2
HEARTBEAT_SECONDS = 900

ACTIVE: Optional["Gossip"] = None
STORE_PATH: Optional[Path] = None

STEPS: List[Callable[[Any, Any], Any]] = []


PREPARE: List[Callable[[Any, Any], None]] = []


def add_prepare(fn: Callable[[Any, Any], None]) -> None:
    if fn not in PREPARE:
        PREPARE.append(fn)


def add_step(fn: Callable[[Any, Any], Any]) -> None:
    if fn not in STEPS:
        STEPS.append(fn)


def wake() -> None:
    active = ACTIVE
    if active is not None:
        active.wake()


def heard_now() -> Dict[str, Dict[str, Any]]:
    active = ACTIVE
    if active is None:
        return {}
    try:
        return active.store.heard(active.held_list(), hlc.wall_ms())
    except sqlite3.Error as exc:
        log.warning("meshdata_heard_failed", error=type(exc).__name__)
        return {}


def wake_on_link(_peer: str) -> None:
    wake()


def member_links(lst: Any, own_iid: str, registry: Any, mesh_api: Any) -> List[Tuple[str, Any]]:
    if registry is None or not capabilities.mesh_on() or not isinstance(lst, RosterV2) or direction.listed_one_way(lst, own_iid):
        return []
    from src.core.computers import mesh_choice
    eligible = set(mesh_choice.eligible_ids(lst, own_iid))
    return [(iid, client) for iid, client in registry.connected()
            if iid in eligible and mesh_api.trusted(iid) is not None and not mesh_api.on_demand(iid)
            and capabilities.has(registry.capabilities(iid), capabilities.CAP_MESH)
            and not direction.contained(iid) and not direction.listed_one_way(lst, iid) and not direction.is_one_way_toward(iid)]


class Gossip:

    def __init__(self, store: RecordStore, *, links_getter: Callable[[], Any], signing: Signing, held_list: Callable[[], Any],
                 label: Callable[[], str], app_version: str, own_iid: str, up_since_ms: Optional[int] = None,
                 members: Optional[Callable[[Any], List[Tuple[str, Any]]]] = None) -> None:
        self.store, self.signing, self.held_list = store, signing, held_list
        self._links, self._label, self._version, self._iid = links_getter, label, app_version, own_iid
        self._up_since = up_since_ms if up_since_ms is not None else hlc.wall_ms()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._wake: Optional[asyncio.Event] = None
        self.last_results: Dict[str, str] = {}
        self._members_fn = members
        self._settled: Dict[str, Tuple[str, float]] = {}
        self.pass_gen: Optional[int] = None

    def _members(self, lst: Any) -> List[Tuple[str, Any]]:
        if self._members_fn is not None:
            return self._members_fn(lst)
        from src.core.federation import mesh_peers
        from src.core.computers import mesh
        return member_links(lst, self._iid, mesh_peers.REGISTRY, mesh)

    def member_pairs(self, lst: Any) -> List[Tuple[str, Any]]:
        return self._members(lst)

    def wake(self) -> None:
        loop, event = self._loop, self._wake
        if loop is not None and event is not None:
            loop.call_soon_threadsafe(event.set)

    def _publish(self, lst: Any, member_ids: Optional[List[str]] = None, gen: Optional[int] = None) -> None:
        for hook in list(PREPARE):
            try:
                hook(self, lst)
            except Exception as exc:  # noqa: BLE001
                log.warning("meshdata_prepare_failed", error=type(exc).__name__)
        self.store.reconcile(lst, self.signing, gen=gen)
        self.store.prune(lst, gen=gen)
        links = self._links()
        ids = [iid for iid, _client in links.connected_clients()] if links is not None else []
        ids += [i for i in (member_ids or []) if i not in ids]
        card = status.build(self._label(), self._version, [i for i in ids if lst.entry(i) is not None], self._up_since)
        last = self.store.own_stamp_ms(status.KIND, self._iid)
        due = last is None or hlc.wall_ms() - last >= HEARTBEAT_SECONDS * 1000
        self.store.put_own(status.KIND, self._iid, card, self.signing, force=due, gen=gen)
        self.store.put_own(withhold.KIND, self._iid, withhold.build(direction.one_way_ids()), self.signing, gen=gen)
        self.store.gc(hlc.wall_ms())

    def peers(self, lst: Any) -> List[Any]:
        links = self._links()
        star = [] if links is None else [
            (iid, client) for iid, client in links.connected_clients()
            if capabilities.has(links.capabilities(iid), capabilities.CAP_MESH) and lst.entry(iid) is not None
            and not direction.contained(iid) and not direction.listed_one_way(lst, iid) and not direction.is_one_way_toward(iid)]
        seen = {iid for iid, _client in star}
        return star + [(iid, client) for iid, client in self._members(lst) if iid not in seen]

    async def _one(self, iid: str, client: Any, lst: Any, slots: asyncio.Semaphore, gen: Optional[int] = None) -> None:
        post = exchange.post_via(client)

        async def call(body: Dict[str, Any]) -> Dict[str, Any]:
            code, answer = await post("POST", SYNC_PATH, body)
            if code != 200 or not isinstance(answer, dict):
                raise wire.ExchangeError(f"http {code}")
            return answer

        async with slots:
            digest = (await asyncio.to_thread(self.store.view, lst, iid))[1]
            held = self._settled.get(iid)
            if held is not None and held[0] == digest and time.monotonic() - held[1] < PERIODIC_SECONDS:
                self.last_results[iid] = "settled"
                return
            try:
                result, accepted = await wire.run_sync(self.store, call, lst, iid, gen=gen)
            except (wire.ExchangeError, PeerUnreachable, PeerRefused, TimeoutError, OSError) as exc:
                self._settled.pop(iid, None)
                self.last_results[iid] = type(exc).__name__
                log.info("meshdata_sync_failed", peer=iid, error=type(exc).__name__)
                return
        self.last_results[iid] = result
        if result == wire.RESULT_OK and not accepted:
            if iid not in self._settled:
                log.info("meshdata_pair_unsettled", peer=iid)
            self._settled[iid] = (digest, time.monotonic())
        else:
            self._settled.pop(iid, None)
        if accepted:
            log.info("meshdata_sync_accepted", peer=iid, accepted=accepted)
            self.wake()

    async def pass_once(self) -> None:
        gen = self.pass_gen = self.store.generation
        lst = await asyncio.to_thread(self.held_list)
        if not isinstance(lst, RosterV2):
            return
        self._settled = {k: v for k, v in self._settled.items() if lst.entry(k) is not None}
        member_ids = [iid for iid, _client in self._members(lst)]
        await asyncio.to_thread(self._publish, lst, member_ids, gen)
        for step in list(STEPS):
            try:
                await step(self, lst)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("meshdata_step_failed", error=type(exc).__name__)
        slots = asyncio.Semaphore(MAX_CONCURRENT_PEERS)
        await asyncio.gather(*(self._one(iid, client, lst, slots, gen) for iid, client in self.peers(lst)))

    async def run(self) -> None:
        self._loop, self._wake = asyncio.get_running_loop(), asyncio.Event()
        self._wake.set()
        woken = True
        while True:
            if woken:
                await asyncio.sleep(DEBOUNCE_SECONDS)
            self._wake.clear()
            try:
                await self.pass_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("meshdata_pass_failed", error=type(exc).__name__)
            period = PERIODIC_SECONDS * (1 + random.uniform(-JITTER_FRACTION, JITTER_FRACTION))
            try:
                await asyncio.wait_for(self._wake.wait(), period)
                woken = True
            except asyncio.TimeoutError:
                woken = False


def forget_pack(own_iid: str) -> bool:
    active = ACTIVE
    if active is not None:
        active.store.clear()
        return True
    if STORE_PATH is None or not STORE_PATH.exists():
        return False
    RecordStore(STORE_PATH, own_iid).clear()
    return True


async def start(*, state_dir: Callable[[], Any], links_getter: Callable[[], Any], signing: Signing, held_list: Callable[[], Any],
                label: Callable[[], str], app_version: str, own_iid: str) -> None:
    global ACTIVE, STORE_PATH
    if not capabilities.mesh_on():
        return
    STORE_PATH = Path(state_dir()) / FILENAME
    try:
        store = await asyncio.to_thread(RecordStore, STORE_PATH, own_iid, hlc.wall_ms, signing)
    except (sqlite3.DatabaseError, OSError) as exc:
        log.warning("meshdata_store_unavailable", error=type(exc).__name__)
        return
    service = Gossip(store, links_getter=links_getter, signing=signing, held_list=held_list, label=label, app_version=app_version, own_iid=own_iid)
    ACTIVE = service
    try:
        await service.run()
    finally:
        ACTIVE = None
