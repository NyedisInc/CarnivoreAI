
from __future__ import annotations

import asyncio
import hashlib
import ssl
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import structlog

from src.core.computers.mux import frames as mf
from src.core.computers.mux.session import MuxError, MuxSession
from src.core.computers.tls_identity import LinkIdentity, client_link_ctx, pinned_certs
from src.core.pack.machines.interim_policy import GAP_SECONDS, ObservedSpan, Peer, Standing, Walk
from src.core.pack.machines.roster_doc import Roster, RosterComputer

log = structlog.get_logger(__name__)

CONNECT_TIMEOUT = 5.0
HELLO_TIMEOUT = 2.0
Connect = Callable[[str, int, ssl.SSLContext], Awaitable[Tuple[asyncio.StreamReader, asyncio.StreamWriter]]]
RelayConnect = Callable[[RosterComputer, ssl.SSLContext], Awaitable[Optional[Tuple[asyncio.StreamReader, asyncio.StreamWriter]]]]


async def _tls_connect(host: str, port: int, ctx: ssl.SSLContext) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    return await asyncio.wait_for(asyncio.open_connection(host, port, ssl=ctx, server_hostname=host, ssl_handshake_timeout=CONNECT_TIMEOUT),
                                  CONNECT_TIMEOUT)


async def _first(attempts: Sequence[Awaitable[Tuple[asyncio.StreamReader, asyncio.StreamWriter]]]) -> Optional[Tuple[asyncio.StreamReader, asyncio.StreamWriter]]:
    pending = {asyncio.ensure_future(a) for a in attempts}
    winner: Optional[Tuple[asyncio.StreamReader, asyncio.StreamWriter]] = None
    try:
        while pending and winner is None:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task.exception() is not None:
                    continue
                if winner is None:
                    winner = task.result()
                else:
                    task.result()[1].close()
    finally:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in pending:
            if task.done() and not task.cancelled() and task.exception() is None:
                task.result()[1].close()
    return winner


async def probe(entry: RosterComputer, identity: LinkIdentity, *, connect: Connect = _tls_connect,
                relay_connect: Optional[RelayConnect] = None) -> Tuple[bool, Optional[Dict[str, Any]]]:
    pins = pinned_certs(entry.ders(), own_link_fid=identity.cert.link_fid)
    if not pins:
        return False, None
    ctx = await asyncio.to_thread(client_link_ctx, identity, pins)
    shas = {c.cert_sha256 for c in pins}
    conn: Optional[Tuple[asyncio.StreamReader, asyncio.StreamWriter]] = None
    if entry.link_port and entry.addresses:
        conn = await _first([connect(a, entry.link_port, ctx) for a in entry.addresses])
    if conn is None and relay_connect is not None:
        try:
            conn = await relay_connect(entry, ctx)
        except (OSError, ssl.SSLError, asyncio.TimeoutError, ValueError) as exc:
            log.info("takeover_walk_relay_failed", why=type(exc).__name__)
    if conn is None:
        return False, None
    reader, writer = conn
    ssl_obj = writer.get_extra_info("ssl_object")
    der = ssl_obj.getpeercert(binary_form=True) if ssl_obj is not None else None
    if not der or hashlib.sha256(der).hexdigest() not in shas:
        writer.close()
        return False, None
    hello: Optional[Dict[str, Any]] = None
    session = MuxSession(reader, writer, dialer=False)
    try:
        await session.start({"v": mf.PROTOCOL_VERSION})
        hello = await asyncio.wait_for(session.hello(), HELLO_TIMEOUT)
    except (MuxError, asyncio.TimeoutError, OSError, ssl.SSLError, ValueError):
        hello = None
    finally:
        try:
            await session.close(mf.GO_NORMAL)
        except (MuxError, OSError):
            writer.close()
    return True, hello if isinstance(hello, dict) else None


class LinkHistory:

    def __init__(self) -> None:
        self._since: Dict[str, float] = {}
        self._last: Dict[str, float] = {}

    def observe(self, connected: Iterable[str], now: float) -> None:
        live = set(connected)
        for iid in list(self._since):
            if iid not in live:
                del self._since[iid]
        for iid in live:
            self._since.setdefault(iid, now)
            self._last[iid] = now

    def linked_for(self, iid: str, now: float) -> float:
        return now - self._since[iid] if iid in self._since else 0.0

    def silent(self, iid: str, now: float, never: float = 1e9) -> float:
        return now - self._last[iid] if iid in self._last else never


class Walker:

    def __init__(self, *, identity: LinkIdentity, self_id: str, clock: Callable[[], float], roster: Callable[[], Optional[Roster]],
                 connect: Connect = _tls_connect, relay_connect: Optional[RelayConnect] = None,
                 linked: Callable[[], Iterable[str]] = lambda: ()) -> None:
        self._identity, self._self_id, self._clock, self._roster = identity, self_id, clock, roster
        self._connect, self._relay_connect, self._linked = connect, relay_connect, linked
        self.spans: Dict[str, ObservedSpan] = {}
        self._reach: Dict[str, Tuple[float, float]] = {}
        self.walk: Optional[Walk] = None

    async def round(self) -> Dict[str, Dict[str, Any]]:
        roster = self._roster()
        if roster is None:
            return {}
        live = set(self._linked())
        others: List[RosterComputer] = [e for e in roster.computers if e.install_id != self._self_id and e.install_id not in live]
        results = await asyncio.gather(*(probe(e, self._identity, connect=self._connect, relay_connect=self._relay_connect) for e in others))
        peers: Dict[str, Peer] = {iid: Peer(True, False) for iid in live if roster.entry(iid) is not None and iid != self._self_id}
        for iid in peers:
            self.spans.setdefault(iid, ObservedSpan(self._clock)).reached()
        hellos: Dict[str, Dict[str, Any]] = {}
        for entry, (ok, hello) in zip(others, results):
            span = self.spans.setdefault(entry.install_id, ObservedSpan(self._clock))
            span.reached() if ok else span.failed()
            peers[entry.install_id] = Peer(ok, bool(hello and hello.get("can_claim") is True))
            if hello is not None:
                hellos[entry.install_id] = hello
        now = self._clock()
        for iid, peer in peers.items():
            first, last = self._reach.get(iid, (now, now))
            self._reach[iid] = (now if now - last > GAP_SECONDS else first, now) if peer.reachable else (0.0, -1e9)
        self.walk = Walk(now, peers)
        return hellos

    def reached_seconds(self, iid: str) -> float:
        first, last = self._reach.get(iid, (0.0, -1e9))
        now = self._clock()
        return last - first if now - last <= GAP_SECONDS else 0.0

    def reset(self) -> None:
        for span in self.spans.values():
            span.reached()
        self._reach.clear()

    def alpha_span(self, alpha: str) -> float:
        span = self.spans.get(alpha)
        return span.seconds() if span is not None else 0.0

    def standing(self, alpha: str, history: LinkHistory) -> Standing:
        now = self._clock()
        silent = {iid: history.silent(iid, now) for iid in (self.walk.peers if self.walk is not None else {})}
        return Standing(now=now, alpha_span=self.alpha_span(alpha), walk=self.walk, silent=silent)
