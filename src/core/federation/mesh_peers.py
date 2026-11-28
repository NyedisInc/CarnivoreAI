
from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

import structlog

from src.core.computers import direction, mesh, mesh_choice
from src.core.computers.link_listener import failure_fields
from src.core.computers.mesh_link import MeshSession
from src.core.federation import mesh_grants, peer_hosts, peer_sockets, shadow_rows
from src.core.federation.fed_key import fid_for
from src.core.federation.grants import decode_public_key
from src.core.federation.mesh_client import MeshPeerClient, MeshTransport
from src.core.federation.peer_client import PeerClient
from src.core.federation.peer_link import CONNECTED, DISCONNECTED, PeerLink
from src.core.pack.machines.roster_v2 import RosterV2

log = structlog.get_logger(__name__)

_GUARDED = (OSError, ValueError, RuntimeError, sqlite3.Error)

CONNECT_SECONDS = 10.0
TOUCH_SECONDS = 30.0


@dataclass
class _Entry:

    session: MeshSession
    transport: MeshTransport
    link: Optional[PeerLink]


class MeshPeers:

    def __init__(self, *, open_db: Callable[[], sqlite3.Connection], self_iid: str, fed_dir: Path, sign: Callable[[bytes], str],
                 trusted: Callable[[str], Any] = mesh.trusted, ensure: Callable[..., Any] = mesh.ensure,
                 touch: Callable[[str], None] = mesh.touch) -> None:
        self._open_db, self._iid, self._fed_dir, self._sign = open_db, self_iid, Path(fed_dir), sign
        self._trusted, self.ensure, self._touch = trusted, ensure, touch
        self._entries: dict = {}
        self._star: dict = {}
        self._lst: Any = None
        self._paused = False
        self._ready: dict = {}
        self._waiting: dict = {}
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mesh-peers")
        self._stopped = False
        self._order = asyncio.Lock()

    def _live(self, iid: str) -> Optional[PeerLink]:
        entry = self._entries.get(iid)
        return entry.link if entry is not None else None

    def holds(self, iid: str) -> bool:
        return iid in self._entries

    def client(self, iid: str) -> Optional[PeerClient]:
        link = self._live(iid)
        client = link.live_client() if link is not None else None
        if client is not None:
            self._touch(iid)
        return client

    def peek(self, iid: str) -> Optional[PeerClient]:
        link = self._live(iid)
        return link.live_client() if link is not None else None

    def touch(self, iid: str) -> None:
        self._touch(iid)

    def state(self, iid: str) -> str:
        link = self._live(iid)
        return link.state if link is not None else DISCONNECTED

    def minor(self, iid: str) -> int:
        link = self._live(iid)
        return link.minor if link is not None else 0

    def capabilities(self, iid: str) -> Optional[List[str]]:
        link = self._live(iid)
        return list(link.capabilities) if link is not None and link.live_client() is not None else None

    def connected(self) -> List[Tuple[str, PeerClient]]:
        out = []
        for iid, entry in self._entries.items():
            client = entry.link.live_client() if entry.link is not None else None
            if client is not None:
                out.append((iid, client))
        return out

    async def session_changed(self, s: MeshSession, up: bool) -> None:
        try:
            async with self._order:
                await (self._up(s) if up else self._down(s))
        except _GUARDED as exc:
            log.warning("mesh_peers_session_failed", peer=s.peer[:8], up=up, **failure_fields(exc))

    def _upsert(self, s: MeshSession, lst: RosterV2) -> str:
        entry, own = lst.entry(s.peer), lst.entry(self._iid)
        if entry is None or own is None:
            return "missing" if entry is None else "self"
        gid = mesh_grants.grant_id_for(s.peer, self._iid, own.fed_public_key, s.own_sha)
        with closing(self._open_db()) as conn:
            row = peer_hosts.upsert_mesh(conn, install_id=s.peer, label=entry.label, grant_id=gid, fid=fid_for(decode_public_key(entry.fed_public_key)))
        return "star" if row is None else "ok"

    async def _up(self, s: MeshSession) -> None:
        lst = self._trusted(s.peer)
        if not isinstance(lst, RosterV2) or self._stopped:
            self._waiting[s.peer] = s
            return
        self._waiting.pop(s.peer, None)
        word = await asyncio.to_thread(self._upsert, s, lst)
        if word in ("missing", "self"):
            log.warning("mesh_peers_no_entry", peer=s.peer[:8], side="peer" if word == "missing" else "self")
            self._waiting[s.peer] = s
            return
        if word == "star":
            log.info("mesh_peers_star_owns", peer=s.peer[:8])
            self._star[s.peer] = s
            return
        if s.mux.closed.is_set() or self._stopped:
            return
        await self._drop(s.peer)
        transport = MeshTransport(s, self._iid, self._fed_dir)
        link = None
        if not direction.listed_one_way(lst, self._iid):
            link = self._link(s, transport)
            link.start()
        self._entries[s.peer] = _Entry(s, transport, link)

    def _link(self, s: MeshSession, transport: MeshTransport) -> PeerLink:
        peer = s.peer
        return PeerLink(peer_install_id=peer, establish=transport.establish,
                        make_client=lambda r: MeshPeerClient(r, session=s, self_iid=self._iid, sign=lambda m: self._sign(m), trusted=self._trusted),
                        on_state=lambda state, _protocol: self._on_link_state(peer, state), on_beat=None)

    def _on_link_state(self, iid: str, state: str) -> None:
        if state == CONNECTED:
            event = self._ready.pop(iid, None)
            if event is not None:
                event.set()
            for listener in list(_CONNECT_LISTENERS):
                try:
                    listener(iid)
                except RuntimeError as exc:
                    log.warning("mesh_peers_listener_failed", peer=iid[:8], error=type(exc).__name__)
        self._write_state(iid, state)

    def _write_state(self, iid: str, state: str) -> None:
        try:
            self._pool.submit(self._state_job, iid, state)
        except RuntimeError:
            return

    def _state_job(self, iid: str, state: str) -> None:
        try:
            with closing(self._open_db()) as conn:
                peer_hosts.set_mesh_state(conn, iid, state)
        except (sqlite3.Error, OSError) as exc:
            log.warning("mesh_peers_state_failed", peer=iid[:8], **failure_fields(exc))

    async def _drop(self, iid: str) -> None:
        entry = self._entries.pop(iid, None)
        if entry is not None:
            if entry.link is not None:
                await entry.link.stop()
            await entry.transport.close()

    async def _down(self, s: MeshSession) -> None:
        self._waiting.pop(s.peer, None)
        if self._star.get(s.peer) is s:
            self._star.pop(s.peer, None)
        gid = s.extra.get("grant_id")
        if gid:
            await peer_sockets.close_grant(gid)
        entry = self._entries.get(s.peer)
        if entry is not None and entry.session is s:
            await self._drop(s.peer)
        self._write_state(s.peer, DISCONNECTED)

    async def list_changed(self, lst: Any, in_grace: bool) -> None:
        if self._stopped:
            return
        if in_grace:
            self._paused = True
            await self._pause()
            return
        if isinstance(lst, RosterV2):
            self._lst, self._paused = lst, False
            try:
                async with self._order:
                    await self._reconcile(lst)
                    for s in [w for w in self._waiting.values() if not w.mux.closed.is_set()]:
                        await self._up(s)
            except _GUARDED as exc:
                log.warning("mesh_peers_list_failed", **failure_fields(exc))
        for fn in list(_LIST_LISTENERS):
            try:
                fn(lst)
            except Exception as exc:  # noqa: BLE001
                log.warning("mesh_list_listener_failed", error_type=type(exc).__name__)

    async def star_row_gone(self, iid: str) -> None:
        try:
            async with self._order:
                s = self._star.pop(iid, None)
                if s is None:
                    entry = self._entries.get(iid)
                    s = entry.session if entry is not None else None
                if s is not None and not s.mux.closed.is_set() and not self._stopped:
                    await self._up(s)
        except _GUARDED as exc:
            log.warning("mesh_peers_star_gone_failed", peer=iid[:8], **failure_fields(exc))

    async def _pause(self) -> None:
        try:
            async with self._order:
                for entry in self._entries.values():
                    if entry.link is not None:
                        await entry.link.stop()
                        entry.link = None
        except _GUARDED as exc:
            log.warning("mesh_peers_pause_failed", **failure_fields(exc))

    async def connect(self, iid: str, timeout: Optional[float] = None) -> Optional[PeerClient]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + (CONNECT_SECONDS if timeout is None else timeout)
        client = self.client(iid)
        if client is not None:
            return client
        if self._paused or (isinstance(self._lst, RosterV2) and direction.listed_one_way(self._lst, self._iid)):
            return None
        if not await self.ensure(iid, max(0.0, deadline - loop.time())):
            return None
        while loop.time() < deadline:
            entry = self._entries.get(iid)
            if entry is not None and entry.link is None:
                return None
            client = self.client(iid)
            if client is not None:
                return client
            event = self._ready.setdefault(iid, asyncio.Event())
            try:
                await asyncio.wait_for(event.wait(), min(0.2, max(0.0, deadline - loop.time())))
            except asyncio.TimeoutError:
                continue
            self._ready.pop(iid, None)
        return self.client(iid)

    def _gone_rows(self, eligible: set) -> List[peer_hosts.PeerRow]:
        with closing(self._open_db()) as conn:
            rows = [r for r in peer_hosts.list_peers(conn, include_mesh=True)
                    if r.back_kind == peer_hosts.MESH_BACK_KIND and r.peer_install_id not in eligible]
            for row in rows:
                shadow_rows.remove_peer(conn, row.key)
                peer_hosts.delete_mesh(conn, row.peer_install_id)
        return rows

    async def _reconcile(self, lst: RosterV2) -> None:
        from src.core.federation import peer_listing, peer_listing_push

        eligible = set(mesh_choice.eligible_ids(lst, self._iid))
        for row in await asyncio.to_thread(self._gone_rows, eligible):
            await self._drop(row.peer_install_id)
            peer_listing.forget(row.peer_install_id)
            peer_listing_push.drop(row.peer_install_id)
        one_way = direction.listed_one_way(lst, self._iid)
        for iid, entry in list(self._entries.items()):
            if one_way and entry.link is not None:
                await entry.link.stop()
                entry.link = None
            elif not one_way and entry.link is None and iid in eligible:
                entry.link = self._link(entry.session, entry.transport)
                entry.link.start()

    def _missing_rows(self, ready: List[Tuple[str, MeshSession, RosterV2]]) -> List[str]:
        restored = []
        with closing(self._open_db()) as conn:
            for iid, session, lst in ready:
                if peer_hosts.get(conn, iid, include_mesh=True) is None and self._upsert(session, lst) == "ok":
                    restored.append(iid)
        return restored

    async def restore_rows(self) -> None:
        if self._stopped or self._paused or not self._entries:
            return
        try:
            async with self._order:
                lst = self._lst
                if not isinstance(lst, RosterV2):
                    return
                eligible = set(mesh_choice.eligible_ids(lst, self._iid))
                ready = []
                for iid, entry in list(self._entries.items()):
                    pinned = self._trusted(iid) if iid in eligible and not entry.session.mux.closed.is_set() else None
                    if isinstance(pinned, RosterV2):
                        ready.append((iid, entry.session, pinned))
                for iid in await asyncio.to_thread(self._missing_rows, ready) if ready else []:
                    self._write_state(iid, self.state(iid))
                    log.info("mesh_peers_row_restored", peer=iid[:8])
        except _GUARDED as exc:
            log.warning("mesh_peers_restore_failed", **failure_fields(exc))

    async def stop(self) -> None:
        self._stopped = True
        for event in self._ready.values():
            event.set()
        for iid in list(self._entries):
            await self._drop(iid)
        await asyncio.to_thread(self._pool.shutdown, wait=True)


REGISTRY: Optional[MeshPeers] = None

_CONNECT_LISTENERS: List[Callable[[str], None]] = []


_LIST_LISTENERS: List[Callable[[Any], None]] = []


def add_list_listener(fn: Callable[[Any], None]) -> None:
    if fn not in _LIST_LISTENERS:
        _LIST_LISTENERS.append(fn)


def add_connect_listener(fn: Callable[[str], None]) -> None:
    if fn not in _CONNECT_LISTENERS:
        _CONNECT_LISTENERS.append(fn)


def session_client(links: Any, iid: str) -> Optional[PeerClient]:
    star = links.client(iid) if links is not None else None
    if star is not None or REGISTRY is None:
        return star
    return REGISTRY.client(iid)


def session_state(links: Any, iid: str) -> str:
    star = links.state(iid) if links is not None else DISCONNECTED
    if REGISTRY is None or not REGISTRY.holds(iid):
        return star
    return CONNECTED if links is not None and links.client(iid) is not None else REGISTRY.state(iid)


def session_minor(links: Any, iid: str) -> int:
    if links is not None and (REGISTRY is None or links.client(iid) is not None):
        return links.minor(iid)
    return REGISTRY.minor(iid) if REGISTRY is not None else 0


def session_clients(links: Any) -> List[Tuple[str, PeerClient]]:
    star = list(links.connected_clients()) if links is not None else []
    if REGISTRY is None:
        return star
    seen = {iid for iid, _ in star}
    return star + [(iid, c) for iid, c in REGISTRY.connected() if iid not in seen]


def holds_live(iid: str) -> bool:
    return REGISTRY is not None and REGISTRY.holds(iid)


async def star_row_gone(iid: str) -> None:
    if REGISTRY is not None:
        await REGISTRY.star_row_gone(iid)


async def connect(links: Any, iid: str) -> Optional[PeerClient]:
    star = links.client(iid) if links is not None else None
    if star is not None or REGISTRY is None:
        return star
    return await REGISTRY.connect(iid)


def keep_alive(iid: str) -> Optional["asyncio.Task[None]"]:
    reg = REGISTRY
    if reg is None or not reg.holds(iid):
        return None

    async def _run() -> None:
        while True:
            reg._touch(iid)
            await asyncio.sleep(TOUCH_SECONDS)

    return asyncio.get_running_loop().create_task(_run(), name="mesh-keep-alive")
