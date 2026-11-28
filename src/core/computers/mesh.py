
from __future__ import annotations

import asyncio
import hashlib
import random
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

import structlog

from src.core.computers import mesh_choice
from src.core.computers.link_dialer import CERT_MISMATCH, LOCAL_NETWORK_BLOCKED, REFUSED, UNREACHABLE, LinkDialer
from src.core.computers.link_listener import LINKED, NO_HELLO, Member, failure_fields
from src.core.computers.member_listener import MemberListener
from src.core.computers.mesh_link import (LIST_SERVICE, MESH_ALPN, PEER_API, MeshSession, Summary, fetch_list, newer, open_session, serve_list,
                                          summary_of)
from src.core.computers.mux import frames as mf
from src.core.computers.mux.session import MuxError, MuxSession, MuxStream
from src.core.computers.tls_identity import LinkCert, LinkIdentity, pinned_certs
from src.core.hosts.ssh_master import backoff_delay
from src.core.pack.machines import capabilities, roster_v2
from src.core.pack.machines.roster_v2 import RosterV2
from src.core.resource_push import topics

log = structlog.get_logger(__name__)

__all__ = ["MESH_ALPN", "LIST_SERVICE", "MeshLinks", "allowed_peers", "attach", "detach", "current_mux", "ensure", "list_changed", "on_demand", "snapshot", "touch", "trusted", "trusted_pin"]

MAX_MESH_LINKS = 32
PENDING_PER_PEER = 2
PENDING_TOTAL = 16
DUP_WINDOW_SECONDS = 10.0
STAGGER_SECONDS = 4.0
STAGGER_JITTER = 2.0
ALPHA_RELEASE_SECONDS = 60.0
TICK_SECONDS = 15.0
FETCH_DEBOUNCE = 2.0
TAKEOVER_GRACE_SECONDS = 120.0
MAX_ON_DEMAND = 8
ON_DEMAND_IDLE_SECONDS = 120.0
_BAD_DIALS = frozenset({UNREACHABLE, REFUSED, LOCAL_NETWORK_BLOCKED, CERT_MISMATCH})


def peer_certs(lst: Any, self_iid: str, own_link_fid: str) -> Dict[str, List[LinkCert]]:
    out: Dict[str, List[LinkCert]] = {}
    for iid in mesh_choice.eligible_ids(lst, self_iid):
        certs = pinned_certs(lst.entry(iid).ders(), own_link_fid=own_link_fid)
        if certs:
            out[iid] = certs
    return out


def allowed_peers(lst: Any, self_iid: str, own_link_fid: str) -> Dict[str, str]:
    return {c.cert_sha256: iid for iid, certs in peer_certs(lst, self_iid, own_link_fid).items() for c in certs}


async def _no_session(s: MeshSession, up: bool) -> None:
    pass


async def _no_list(lst: Any, in_grace: bool) -> None:
    pass


async def _no_tick() -> None:
    pass


class MeshLinks:

    def __init__(self, *, identity: LinkIdentity, iid: str, listener: MemberListener, custody: Callable[[], Any],
                 after_change: Callable[[], Awaitable[None]], star_linked: Callable[[str], float],
                 backoff: Callable[[int], float] = backoff_delay, stagger: float = STAGGER_SECONDS, jitter: float = STAGGER_JITTER,
                 clock: Callable[[], float] = time.monotonic, reachable: Callable[[], Optional[frozenset]] = lambda: None,
                 notify: Callable[[], None] = lambda: None, on_session: Callable[[MeshSession, bool], Awaitable[None]] = _no_session,
                 on_list: Callable[[Any, bool], Awaitable[None]] = _no_list, on_tick: Callable[[], Awaitable[None]] = _no_tick) -> None:
        self._on_session, self._on_list, self._on_tick = on_session, on_list, on_tick
        self._identity, self._iid, self._listener, self._custody = identity, iid, listener, custody
        self._reachable, self._notify = reachable, notify
        self._after_change, self._star_linked, self._stagger, self._jitter, self._clock = after_change, star_linked, stagger, jitter, clock
        self._fid = identity.cert.link_fid
        self._lst: Any = None
        self._summary_d: Optional[Summary] = None
        self._blob: Optional[bytes] = None
        self._snapped = False
        self._stored_v2: Optional[RosterV2] = None
        self._master: Optional[str] = None
        self._certs: Dict[str, List[LinkCert]] = {}
        self._allowed: Dict[str, str] = {}
        self._sessions: Dict[str, MeshSession] = {}
        self._pending: Dict[str, int] = {}
        self._hold: Dict[str, float] = {}
        self._dial_ids: Set[str] = set()
        self._wanted: frozenset = frozenset()
        self._refused: Dict[str, Set[str]] = {}
        self._claims: Dict[str, Summary] = {}
        self._hold_timers: Dict[str, asyncio.TimerHandle] = {}
        self._good: Optional[Tuple[RosterV2, Dict[str, str]]] = None
        self._grace_until: Optional[float] = None
        self._grace_spent = False
        self._marks: Dict[str, Tuple[frozenset, bool]] = {}
        self._fetching: Dict[str, "asyncio.Task[None]"] = {}
        self._again: Set[str] = set()
        self._tasks: Set["asyncio.Task[None]"] = set()
        self._lock = asyncio.Lock()
        self._changing = False
        self._tick_task: Optional["asyncio.Task[None]"] = None
        self._stopped = False
        self._excl = mesh_choice.Exclusions()
        self._on_demand: Dict[str, float] = {}
        self._up: Dict[str, asyncio.Event] = {}
        self._view: Tuple[Dict[str, Any], ...] = ()
        self._switch = "no_list"
        self._dialer = LinkDialer(identity=identity, hub=self, rows=self._row, alpn=MESH_ALPN, idle_while=self._idle, on_change=self._dial_changed, backoff=backoff)

    def connected(self) -> frozenset:
        return frozenset(self._sessions)

    def relayed(self) -> frozenset:
        return frozenset()

    def _row(self, iid: str) -> Any:
        return self._lst.entry(iid) if isinstance(self._lst, RosterV2) and iid in self._certs else None

    def _idle(self, iid: str) -> bool:
        return iid in self._sessions or self._hold.get(iid, 0.0) > self._clock()

    def iid_for_sha(self, sha: str) -> Optional[str]:
        return self._allowed.get(sha)

    @staticmethod
    def _sha_of(writer: asyncio.StreamWriter) -> Optional[str]:
        ssl_obj = writer.get_extra_info("ssl_object")
        try:
            der = ssl_obj.getpeercert(binary_form=True) if ssl_obj is not None else None
        except ValueError:
            return None
        return hashlib.sha256(der).hexdigest() if der else None

    def _pinned(self, s: MeshSession) -> bool:
        return self._allowed.get(s.cert_sha) == s.peer

    def _held_over(self, s: MeshSession) -> bool:
        return self._grace_until is not None and self._good is not None and self._good[1].get(s.cert_sha) == s.peer

    async def serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, relayed: bool = False) -> str:
        sha = self._sha_of(writer)
        peer = self._allowed.get(sha) if sha else None
        if peer is None or sha is None:
            writer.close()
            return NO_HELLO
        res = await open_session(reader, writer, peer=peer, accepting=False, own_iid=self._iid, summary=lambda: self._summary_d,
                                 on_open=self._handler(peer), already_linked=lambda p: p in self._sessions, cert_sha=sha,
                                 own_fallback=self._identity.cert.cert_sha256)
        if isinstance(res, str):
            return res
        if not await self.register(res):
            return NO_HELLO
        await asyncio.shield(res.mux.wait_closed())
        return LINKED

    async def accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, iid: str) -> None:
        sha = self._sha_of(writer)
        if (self._stopped or sha is None or self._allowed.get(sha) != iid or len(self._sessions) >= MAX_MESH_LINKS
                or self._pending.get(iid, 0) >= PENDING_PER_PEER or sum(self._pending.values()) >= PENDING_TOTAL):
            log.info("mesh_link_refused", peer=iid[:8])
            writer.close()
            return
        self._pending[iid] = self._pending.get(iid, 0) + 1
        try:
            res = await open_session(reader, writer, peer=iid, accepting=True, own_iid=self._iid, summary=lambda: self._summary_d,
                                     on_open=self._handler(iid), already_linked=lambda p: False, cert_sha=sha,
                                     own_fallback=self._identity.cert.cert_sha256)
        finally:
            self._pending[iid] -= 1
            if not self._pending[iid]:
                del self._pending[iid]
        if isinstance(res, MeshSession):
            await self.register(res)

    @staticmethod
    def _keep_new(old: MeshSession, new: MeshSession, own_iid: str, now: float) -> bool:
        if now - old.started_at >= DUP_WINDOW_SECONDS:
            return True
        old_dialer, new_dialer = (own_iid if old.dialed_by_me else old.peer), (own_iid if new.dialed_by_me else new.peer)
        return new_dialer < old_dialer or new_dialer == old_dialer

    async def register(self, s: MeshSession) -> bool:
        if self._stopped or not self._pinned(s):
            await s.mux.close(mf.GO_NORMAL if self._stopped else mf.GO_REMOVED)
            return False
        old = self._sessions.get(s.peer)
        if old is not None and not old.mux.closed.is_set():
            keep_new = self._keep_new(old, s, self._iid, self._clock())
            await (old if keep_new else s).mux.close(mf.GO_REPLACED)
            if not keep_new:
                self._wake(s.peer)
                return True
            if self._stopped or not self._pinned(s):
                await s.mux.close(mf.GO_NORMAL if self._stopped else mf.GO_REMOVED)
                return False
        self._sessions[s.peer] = s
        entry = self._lst.entry(s.peer) if isinstance(self._lst, RosterV2) else None
        if entry is not None:
            from src.core.federation import mesh_grants

            s.extra["grant_id"] = mesh_grants.grant_id_for(self._iid, s.peer, entry.fed_public_key, s.cert_sha)
            await self._session_hook(s, True)
        self._wake(s.peer)
        watcher = asyncio.get_running_loop().create_task(self._on_closed(s), name=f"mesh-closed-{s.peer[:8]}")
        self._tasks.add(watcher)
        watcher.add_done_callback(self._tasks.discard)
        log.info("mesh_link_up", peer=s.peer[:8], dialed_by_me=s.dialed_by_me)
        self._consider(s.peer, s.peer_summary, 0.0)
        self._publish()
        return True

    async def _session_hook(self, s: MeshSession, up: bool) -> None:
        try:
            await self._on_session(s, up)
        except (OSError, ValueError, RuntimeError) as exc:
            log.warning("mesh_session_hook_failed", peer=s.peer[:8], up=up, **failure_fields(exc))

    async def _on_closed(self, s: MeshSession) -> None:
        await s.mux.wait_closed()
        current = self._sessions.get(s.peer)
        if current is not None and current is not s and s.extra.get("grant_id") != current.extra.get("grant_id"):
            await self._close_grant_sockets(s)
        if current is s:
            del self._sessions[s.peer]
            await self._session_hook(s, False)
            self._stagger_hold(s.peer)
            self._dialer.kick(s.peer)
            log.info("mesh_link_down", peer=s.peer[:8])
            self._publish()

    async def _close_grant_sockets(self, s: MeshSession) -> None:
        from src.core.federation import peer_sockets

        gid = s.extra.get("grant_id")
        if gid:
            try:
                await peer_sockets.close_grant(gid)
            except (RuntimeError, OSError) as exc:
                log.warning("mesh_close_grant_failed", peer=s.peer[:8], **failure_fields(exc))

    def _stagger_hold(self, peer: str) -> None:
        if peer < self._iid:
            delay = self._stagger + random.uniform(0.0, self._jitter)
            self._hold[peer] = self._clock() + delay
            old = self._hold_timers.pop(peer, None)
            if old is not None:
                old.cancel()
            self._hold_timers[peer] = asyncio.get_running_loop().call_later(delay, self._hold_ended, peer)

    def _hold_ended(self, peer: str) -> None:
        left = self._hold.get(peer, 0.0) - self._clock()
        if left > 0:
            self._hold_timers[peer] = asyncio.get_running_loop().call_later(left, self._hold_ended, peer)
            return
        self._dialer.kick(peer)

    def _summary(self) -> Optional[Summary]:
        return self._summary_d

    def _held(self) -> Optional[Tuple[Summary, bytes]]:
        return (self._summary_d, self._blob) if self._summary_d is not None and self._blob is not None else None

    def _handler(self, peer: str) -> Callable[[MuxStream], Awaitable[None]]:
        busy = [False]

        async def on_open(stream: MuxStream) -> None:
            if stream.service == PEER_API:
                mux = self.current_mux(peer)
                if mux is None or mux is not stream.session:
                    stream.reset(mf.RST_UNAVAILABLE)
                    return
                from src.core.federation import mesh_listener

                await mesh_listener.bridge_inbound(stream, peer, mux)
                return
            if busy[0]:
                stream.reset(mf.RST_LIMIT)
                return
            busy[0] = True
            try:
                theirs = await serve_list(stream, self._held)
            finally:
                busy[0] = False
            if theirs is not None:
                self._consider(peer, theirs, FETCH_DEBOUNCE)

        return on_open

    def _consider(self, peer: str, theirs: Optional[Summary], delay: float) -> None:
        if theirs is not None and newer(theirs, self._summary_d) and theirs["sha"] not in self._refused.get(peer, ()):
            self._schedule_fetch(peer, delay, claim=theirs)

    def _schedule_fetch(self, peer: str, delay: float = 0.0, claim: Optional[Summary] = None) -> None:
        if claim is not None:
            self._claims[peer] = claim
        task = self._fetching.get(peer)
        if task is not None and not task.done():
            self._again.add(peer)
            return
        self._fetching[peer] = asyncio.get_running_loop().create_task(self._fetch(peer, delay), name=f"mesh-list-{peer[:8]}")

    async def _fetch(self, peer: str, delay: float) -> None:
        claim: Optional[Summary] = None
        try:
            if delay:
                await asyncio.sleep(delay)
            claim = self._claims.pop(peer, None)
            s = self._sessions.get(peer)
            if s is None:
                return
            raw = await fetch_list(s.mux, self._summary_d)
            if raw is None:
                if claim is not None and newer(claim, self._summary_d):
                    self._refused.setdefault(peer, set()).add(claim["sha"])
                return
            sha = roster_v2.sha(roster_v2.blob(raw))
            if await asyncio.to_thread(self._custody().merge_roster_v2, raw, peer):
                await self._after_change()
            else:
                refused = self._refused.setdefault(peer, set())
                refused.add(sha)
                if claim is not None:
                    refused.add(claim["sha"])
                log.info("mesh_list_refused", peer=peer[:8], sha=sha[:12])
        except asyncio.CancelledError:
            raise
        except (MuxError, OSError, ValueError, RuntimeError, asyncio.TimeoutError) as exc:
            log.info("mesh_list_fetch_failed", peer=peer[:8], **failure_fields(exc))
        finally:
            if peer in self._again and not self._stopped:
                self._again.discard(peer)
                self._schedule_fetch(peer)

    async def _snapshot(self) -> None:
        try:
            custody = self._custody()
            held, wire, master = await asyncio.to_thread(lambda: (custody.held_lists(), custody.roster_v2_wire(), custody.settings().master_install_id))
        except (OSError, ValueError, RuntimeError) as exc:
            log.info("mesh_snapshot_failed", **failure_fields(exc))
            held, wire, master = None, None, None
        lst = held[0] if held is not None else None
        parsed = roster_v2.from_wire_v2(wire) if wire is not None else None
        self._stored_v2 = parsed[0] if parsed is not None and parsed[1] is not None else None
        self._master = master
        signed = wire if parsed is not None and isinstance(lst, RosterV2) and parsed[0] == lst else None
        self._lst = lst
        self._summary_d = summary_of(lst, signed)
        self._blob = roster_v2.blob(signed) if signed is not None and self._summary_d is not None else None
        self._snapped = True

    def _release_pending(self, lst: Any, s: MeshSession) -> bool:
        entry = lst.entry(s.peer) if isinstance(lst, RosterV2) else None
        if entry is None or s.cert_sha not in entry.shas():
            return False
        return s.peer == lst.alpha or self._iid == lst.alpha

    def _update_grace(self, lst: Any) -> None:
        if isinstance(lst, RosterV2):
            self._good, self._grace_until, self._grace_spent = (lst, dict(self._allowed)), None, False
            return
        good, stored = self._good, self._stored_v2
        if good is not None and not self._grace_spent and stored is not None and stored == good[0] and stored.alpha != self._master \
                and self._master is not None and stored.entry(self._master) is not None:
            now = self._clock()
            if self._grace_until is None:
                self._grace_until = now + TAKEOVER_GRACE_SECONDS
                log.info("mesh_takeover_hold", master=self._master[:8])
            elif now >= self._grace_until:
                self._grace_spent, self._grace_until = True, None
                log.info("mesh_takeover_hold_over", master=self._master[:8])
            return
        if self._grace_until is not None:
            self._grace_spent = True
        self._grace_until = None

    def current_mux(self, peer: str) -> Optional[MuxSession]:
        s = self._sessions.get(peer)
        return s.mux if s is not None and not s.mux.closed.is_set() else None

    def trusted_pin(self, peer: str) -> Optional[Tuple[RosterV2, str]]:
        s, lst = self._sessions.get(peer), self._lst
        if self._stopped or self._changing or not isinstance(lst, RosterV2) or self._grace_until is not None or s is None or s.mux.closed.is_set():
            return None
        return (lst, s.cert_sha) if self._pinned(s) and not self._release_pending(lst, s) else None

    def trusted(self, peer: str) -> Optional[RosterV2]:
        pin = self.trusted_pin(peer)
        return pin[0] if pin else None

    async def _close_changed_grants(self) -> None:
        from src.core.federation import mesh_grants, peer_sockets

        lst = self._lst
        new: Dict[str, Tuple[frozenset, bool]] = {}
        if isinstance(lst, RosterV2) and self._grace_until is None:
            for peer in mesh_choice.eligible_ids(lst, self._iid):
                entry = lst.entry(peer)
                if entry is not None:
                    ids = frozenset(mesh_grants.grant_id_for(self._iid, peer, entry.fed_public_key, sha) for sha in entry.shas())
                    new[peer] = (ids, entry.one_way)
        old, self._marks = self._marks, new
        for peer, (old_ids, old_one_way) in old.items():
            now = new.get(peer)
            gone = old_ids if now is None or now[1] != old_one_way else old_ids - now[0]
            for gid in gone:
                await peer_sockets.close_grant(gid)

    async def list_changed(self) -> None:
        async with self._lock:
            try:
                await self._list_changed()
            except (OSError, ValueError, RuntimeError, MuxError) as exc:
                log.warning("mesh_list_changed_failed", **failure_fields(exc))

    async def _list_changed(self) -> None:
        if self._stopped:
            return
        self._changing = True
        try:
            await self._snapshot()
            self._certs = await asyncio.to_thread(peer_certs, self._lst, self._iid, self._fid)
            self._allowed = {c.cert_sha256: iid for iid, certs in self._certs.items() for c in certs}
        finally:
            self._changing = False
        self._update_grace(self._lst)
        for gone in [p for p in self._on_demand if p not in self._certs]:
            del self._on_demand[gone]
            self._excl.forget(gone)
        self._switch = mesh_choice.own_switch(self._lst, self._iid)
        for s in list(self._sessions.values()):
            if not (self._pinned(s) or self._release_pending(self._lst, s) or self._held_over(s)):
                await s.mux.close(mf.GO_REMOVED)
        await self._close_changed_grants()
        self._refused.clear()
        self._rechoose(force=True)
        for peer in list(self._sessions):
            self._claims.pop(peer, None)
            self._schedule_fetch(peer)
        try:
            await self._on_list(self._lst, self._grace_until is not None)
        except (OSError, ValueError, RuntimeError) as exc:
            log.warning("mesh_list_hook_failed", **failure_fields(exc))
        self._publish()

    def _dial_changed(self, iid: str) -> None:
        st = self._dialer.dial_state(iid)
        self._excl.observe(iid, st is not None and st["state"] in _BAD_DIALS, self._clock())
        self._publish()

    def _rechoose(self, force: bool = False) -> None:
        std = [p for p in mesh_choice.choose_links(self._lst, self._iid, reachable=self._reachable(), connected=self._sessions.keys(),
                                                   excluded=self._excl.excluded(self._clock())) if p in self._certs]
        for peer in std:
            if peer not in self._dial_ids:
                self._stagger_hold(peer)
        self._dial_ids = set(std)
        wanted = std + [p for p in self._on_demand if p in self._certs and p not in self._dial_ids]
        self._dialer.set_members([Member(p, "", self._certs[p][0], self._certs[p][1] if len(self._certs[p]) > 1 else None) for p in wanted])
        now_wanted = frozenset(wanted)
        if force or now_wanted != self._wanted:
            self._dialer.kick()
        self._wanted = now_wanted

    def _wake(self, peer: str) -> None:
        ev = self._up.pop(peer, None)
        if ev is not None:
            ev.set()

    async def ensure(self, iid: str, timeout: float = 10.0) -> bool:
        if self._stopped or iid not in self._certs or (iid not in self._on_demand and len(self._on_demand) >= MAX_ON_DEMAND):
            return False
        self._on_demand[iid] = self._clock()
        if iid in self._sessions:
            return True
        self._hold.pop(iid, None)
        timer = self._hold_timers.pop(iid, None)
        if timer is not None:
            timer.cancel()
        self._rechoose()
        self._publish()
        try:
            await asyncio.wait_for(self._up.setdefault(iid, asyncio.Event()).wait(), timeout)
        except asyncio.TimeoutError:
            return False
        return iid in self._sessions

    def touch(self, iid: str) -> None:
        if iid in self._on_demand:
            self._on_demand[iid] = self._clock()

    def on_demand(self, iid: str) -> bool:
        return iid in self._on_demand and iid not in self._dial_ids

    async def _sweep(self) -> None:
        async with self._lock:
            try:
                now = self._clock()
                for peer in [p for p, at in self._on_demand.items() if now - at >= ON_DEMAND_IDLE_SECONDS]:
                    del self._on_demand[peer]
                    s = self._sessions.get(peer)
                    if peer not in self._dial_ids and s is not None and s.dialed_by_me:
                        await s.mux.close(mf.GO_NORMAL)
                self._rechoose()
                grace_over = self._grace_until is not None and now >= self._grace_until
                self._publish()
            except (OSError, ValueError, RuntimeError, MuxError) as exc:
                log.warning("mesh_sweep_failed", **failure_fields(exc))
                return
        if grace_over:
            await self.list_changed()

    def _refresh_view(self) -> bool:
        excluded = self._excl.excluded(self._clock())
        ids = mesh_choice.eligible_ids(self._lst, self._iid)
        ids += [p for p, s in self._sessions.items() if p not in ids and not s.mux.closed.is_set()]
        view = []
        for p in ids:
            s = self._sessions.get(p)
            live = s if s is not None and not s.mux.closed.is_set() else None
            dial = self._dialer.dial_state(p)
            if live is not None and self._pinned(live):
                state = "linked"
            elif live is not None and (self._held_over(live) or self._release_pending(self._lst, live)):
                state = "held_over"
            elif p in excluded:
                state = "excluded"
            else:
                state = dial["state"] if dial is not None else "not_held"
            since = live.opened_wall if live is not None else (dial["since"] if dial is not None else None)
            view.append({"install_id": p, "state": state, "since": since, "dialed_by": None if live is None else "this" if live.dialed_by_me else "peer",
                         "standing": p in self._dial_ids, "on_demand": p in self._on_demand})
        changed = tuple(view) != self._view
        self._view = tuple(view)
        return changed

    def _publish(self) -> None:
        if self._refresh_view():
            self._notify()

    def snapshot(self) -> Dict[str, Any]:
        return {"switch": self._switch, "links": list(self._view)}

    async def _tick(self) -> None:
        while True:
            try:
                if not self._snapped:
                    await self.list_changed()
                lst = self._lst
                for peer, s in list(self._sessions.items()):
                    if self._release_pending(lst, s) and self._star_linked(peer) >= ALPHA_RELEASE_SECONDS:
                        log.info("mesh_link_released", peer=peer[:8])
                        await s.mux.close(mf.GO_NORMAL)
                await self._sweep()
                await self._on_tick()
            except asyncio.CancelledError:
                raise
            except (OSError, ValueError, RuntimeError, MuxError) as exc:
                log.warning("mesh_tick_failed", **failure_fields(exc))
            await asyncio.sleep(TICK_SECONDS)

    def start(self) -> None:
        self._listener.attach_mesh(self.accept, self.iid_for_sha)
        self._tick_task = asyncio.get_running_loop().create_task(self._tick(), name="mesh-tick")

    async def stop(self) -> None:
        self._stopped = True
        self._listener.detach_mesh()
        for timer in self._hold_timers.values():
            timer.cancel()
        self._hold_timers.clear()
        tasks = [t for t in (self._tick_task, *self._fetching.values(), *self._tasks) if t is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self._dialer.stop()
        for s in list(self._sessions.values()):
            await s.mux.close(mf.GO_NORMAL)
            await self._close_grant_sockets(s)
        self._sessions.clear()


_ACTIVE: Optional[MeshLinks] = None


def compose_on_list(*hooks: Callable[[Any, bool], Awaitable[None]]) -> Callable[[Any, bool], Awaitable[None]]:
    async def run(lst: Any, in_grace: bool) -> None:
        for hook in hooks:
            await hook(lst, in_grace)
    return run


def _held_v2(rt: Any) -> Optional[Any]:
    try:
        held = rt._roster._wired().runtime.custody.held_lists()
    except RuntimeError:
        return None
    lst = held[0] if held else None
    return lst if isinstance(lst, RosterV2) else None


def attach(rt: Any) -> None:
    global _ACTIVE
    if not capabilities.mesh_on() or rt._roster is None or rt.member_listener is None or rt.identity is None or rt.iid is None:
        return

    def star_linked(iid: str) -> float:
        return rt.takeover.history.linked_for(iid, time.monotonic()) if rt.takeover is not None else 0.0

    from src.core.computers import mesh_removal
    from src.core.federation import mesh_peers

    peers = mesh_peers.REGISTRY = mesh_peers.MeshPeers(open_db=rt.open_db, self_iid=rt.iid, fed_dir=rt.fed_dir, sign=lambda m: rt.fed_key.sign(m))
    held = lambda: _held_v2(rt)  # noqa: E731
    removal = mesh_removal.REMOVAL = mesh_removal.Removal(open_db=rt.open_db, self_iid=rt.iid, held=held,
                                                          steps=mesh_removal.production_steps(notify=rt.notify, held=held))
    _ACTIVE = MeshLinks(identity=rt.identity, iid=rt.iid, listener=rt.member_listener, custody=lambda: rt._roster._wired().runtime.custody,
                        after_change=rt.after_roster_change, star_linked=star_linked,
                        reachable=lambda: rt.takeover.reachable() if rt.takeover is not None else None,
                        notify=lambda: rt.notify(topics.COMPUTERS), on_session=peers.session_changed, on_tick=peers.restore_rows,
                        on_list=compose_on_list(peers.list_changed, removal.list_changed))
    _ACTIVE.start()


async def detach() -> None:
    global _ACTIVE
    links, _ACTIVE = _ACTIVE, None
    if links is not None:
        await links.stop()
    from src.core.federation import mesh_peers

    registry, mesh_peers.REGISTRY = mesh_peers.REGISTRY, None
    if registry is not None:
        await registry.stop()
    from src.core.computers import mesh_removal

    removal, mesh_removal.REMOVAL = mesh_removal.REMOVAL, None
    if removal is not None:
        await removal.stop()


async def list_changed() -> None:
    if _ACTIVE is not None:
        await _ACTIVE.list_changed()


def current_mux(peer: str) -> Optional[MuxSession]:
    return _ACTIVE.current_mux(peer) if _ACTIVE is not None else None


def trusted_pin(peer: str) -> Optional[Tuple[RosterV2, str]]:
    return _ACTIVE.trusted_pin(peer) if _ACTIVE is not None else None


def trusted(peer: str) -> Optional[RosterV2]:
    return _ACTIVE.trusted(peer) if _ACTIVE is not None else None


async def ensure(iid: str, timeout: float = 10.0) -> bool:
    return await _ACTIVE.ensure(iid, timeout) if _ACTIVE is not None else False


def touch(iid: str) -> None:
    if _ACTIVE is not None:
        _ACTIVE.touch(iid)


def on_demand(iid: str) -> bool:
    return _ACTIVE.on_demand(iid) if _ACTIVE is not None else False


def snapshot() -> Optional[Dict[str, Any]]:
    return _ACTIVE.snapshot() if _ACTIVE is not None else None
