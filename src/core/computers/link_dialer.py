
from __future__ import annotations

import asyncio
import errno
import hashlib
import ipaddress
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.computers import store
from src.core.computers.link_listener import ALERTED, LINKED, LinkListener, Member, failure_fields
from src.core.computers.tls_identity import LinkIdentity, client_link_ctx
from src.core.hosts.ssh_master import backoff_delay

log = structlog.get_logger(__name__)

CONNECT_TIMEOUT = 5.0
DIAL_STAGGER = 0.25
SLOW_SECONDS = 300.0
MAX_NAME_ADDRESSES = 4
REFUSED_AFTER_ALERTS = 3

LINKED_STATE, DIALING, UNREACHABLE, LOCAL_NETWORK_BLOCKED = "linked", "dialing", "unreachable", "local_network_blocked"
REFUSED, CERT_MISMATCH = "refused", "cert_mismatch"
_BLOCKED_ERRNOS = frozenset({errno.EHOSTUNREACH, errno.ENETUNREACH})

Dialed = Tuple[str, int, asyncio.StreamReader, asyncio.StreamWriter]


def _private(address: str) -> bool:
    if address.lower().endswith(".local"):
        return True
    try:
        return ipaddress.ip_address(address).is_private
    except ValueError:
        return False


def _failure_state(errors: Sequence[BaseException], targets: Sequence[Tuple[str, int]]) -> str:
    if errors and targets and all(isinstance(e, OSError) and e.errno in _BLOCKED_ERRNOS for e in errors) \
            and all(_private(a) for a, _ in targets):
        return LOCAL_NETWORK_BLOCKED
    if any(isinstance(e, ssl.SSLCertVerificationError) for e in errors):
        return CERT_MISMATCH
    return UNREACHABLE


@dataclass
class _Dial:

    task: "asyncio.Task[None]"
    kick: asyncio.Event
    member: Member
    state: str = DIALING
    since: Optional[float] = None
    last_good: Optional[str] = None
    alerts: int = 0


class LinkDialer:

    def __init__(self, *, identity: LinkIdentity, hub: LinkListener, rows: Callable[[str], Optional[store.LinkRow]],
                 on_change: Optional[Callable[[str], None]] = None, backoff: Callable[[int], float] = backoff_delay,
                 connect_timeout: float = CONNECT_TIMEOUT, stagger: float = DIAL_STAGGER) -> None:
        self._identity, self._hub, self._rows, self._on_change = identity, hub, rows, on_change
        self._backoff, self._timeout, self._stagger = backoff, connect_timeout, stagger
        self._dials: Dict[str, _Dial] = {}

    def set_members(self, members: Sequence[Member]) -> None:
        wanted = {m.peer_install_id: m for m in members}
        for iid in [i for i in self._dials if i not in wanted]:
            self._dials.pop(iid).task.cancel()
        for iid, member in wanted.items():
            if iid in self._dials:
                dial = self._dials[iid]
                if dial.member.shas() != member.shas():
                    dial.kick.set()
                dial.member = member
            else:
                self._dials[iid] = _Dial(task=asyncio.get_running_loop().create_task(self._run(iid), name=f"link-dial-{iid[:8]}"),
                                         kick=asyncio.Event(), member=member)

    def kick(self, iid: Optional[str] = None) -> None:
        for key, dial in self._dials.items():
            if iid is None or key == iid:
                dial.kick.set()

    def dial_state(self, iid: str) -> Optional[Dict[str, Optional[float]]]:
        dial = self._dials.get(iid)
        if dial is None:
            return None
        if iid in self._hub.connected():
            return {"state": LINKED_STATE, "since": None}
        return {"state": dial.state, "since": dial.since}

    async def stop(self) -> None:
        tasks = [d.task for d in self._dials.values()]
        self._dials.clear()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _set(self, iid: str, dial: _Dial, state: str) -> None:
        changed = state != dial.state
        dial.since = (dial.since or time.time()) if state == UNREACHABLE else None
        dial.state = state
        if changed:
            log.info("computer_dial", state=state, peer=iid[:8])
            if self._on_change is not None:
                self._on_change(iid)

    async def _run(self, iid: str) -> None:
        attempt = 0
        while True:
            dial = self._dials.get(iid)
            if dial is None:
                return
            wait = self._backoff(attempt)
            try:
                outcome = await self._round(iid, dial)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.error("computer_dial_failed", peer=iid[:8], **failure_fields(exc))
                outcome = UNREACHABLE
            if outcome == LINKED_STATE:
                attempt = 0
                wait = self._backoff(0)
            else:
                attempt += 1
                if outcome == REFUSED:
                    wait = SLOW_SECONDS
            dial.kick.clear()
            try:
                await asyncio.wait_for(dial.kick.wait(), wait)
            except asyncio.TimeoutError:
                pass

    async def _round(self, iid: str, dial: _Dial) -> str:
        row = self._rows(iid)
        if row is None or not row.addresses or not row.link_port:
            self._set(iid, dial, UNREACHABLE)
            return UNREACHABLE
        member = dial.member
        pins = [c for c in (member.cert, member.next_cert) if c is not None]
        ctx = await asyncio.to_thread(client_link_ctx, self._identity, pins)
        targets = sorted(((a, row.link_port) for a in await self._expand(row.addresses)), key=lambda t: t[0] != dial.last_good)
        conn, errors = await self._dial(targets, ctx, member.shas())
        if conn is None:
            state = _failure_state(errors, targets)
            self._set(iid, dial, state)
            return state
        address, _port, reader, writer = conn
        outcome = await self._hub.serve(reader, writer)
        if outcome == LINKED:
            dial.last_good, dial.alerts = address, 0
            self._set(iid, dial, DIALING)
            return LINKED_STATE
        dial.alerts = dial.alerts + 1 if outcome == ALERTED else 0
        state = REFUSED if dial.alerts >= REFUSED_AFTER_ALERTS else UNREACHABLE
        self._set(iid, dial, state)
        return state

    async def _expand(self, addresses: Sequence[str]) -> List[str]:
        out: List[str] = []
        loop = asyncio.get_running_loop()
        for address in addresses:
            found: List[str] = []
            if address.lower().endswith(".local"):
                try:
                    infos = await asyncio.wait_for(loop.getaddrinfo(address, None, family=socket.AF_INET, type=socket.SOCK_STREAM), self._timeout)
                    found = list(dict.fromkeys(str(info[4][0]) for info in infos))[:MAX_NAME_ADDRESSES]
                except (OSError, asyncio.TimeoutError) as exc:
                    log.info("computer_dial_name_unresolved", error_type=type(exc).__name__)
            for item in found or [address]:
                if item not in out:
                    out.append(item)
        return out

    async def _dial(self, targets: Sequence[Tuple[str, int]], ctx: ssl.SSLContext,
                    shas: frozenset) -> Tuple[Optional[Dialed], List[BaseException]]:
        async def attempt(delay: float, address: str, port: int) -> Dialed:
            await asyncio.sleep(delay)
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(address, port, ssl=ctx, server_hostname=address,
                                        ssl_handshake_timeout=self._timeout), self._timeout)
            ssl_obj = writer.get_extra_info("ssl_object")
            der = ssl_obj.getpeercert(binary_form=True) if ssl_obj is not None else None
            if not der or hashlib.sha256(der).hexdigest() not in shas:
                writer.close()
                raise ssl.SSLCertVerificationError("the member presented a certificate that is not pinned")
            return address, port, reader, writer

        tasks = [asyncio.ensure_future(attempt(i * self._stagger, a, p)) for i, (a, p) in enumerate(targets)]
        winner: Optional[Dialed] = None
        errors: List[BaseException] = []
        pending = set(tasks)
        try:
            while pending and winner is None:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if task.exception() is not None:
                        errors.append(task.exception())  # type: ignore[arg-type]
                    elif winner is None:
                        winner = task.result()
                    else:
                        task.result()[3].close()
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in pending:
                if task.done() and not task.cancelled() and task.exception() is None:
                    task.result()[3].close()
        return winner, errors
