
from __future__ import annotations

import asyncio
import hashlib
import ssl
import time
from typing import Awaitable, Callable, FrozenSet, Optional, Tuple

import structlog

from src.core.computers import store
from src.core.computers.link_listener import failure_fields
from src.core.computers.member_listener import Rendezvous
from src.core.computers.tls_identity import LinkIdentity, client_link_ctx, pinned_certs
from src.core.phone_link.pack_relay import PACK_ALPN

log = structlog.get_logger(__name__)

UNLINKED_SECONDS = 60.0
RELAY_PORT = 443
DIAL_TIMEOUT = 8.0

Conn = Tuple[asyncio.StreamReader, asyncio.StreamWriter]
Connect = Callable[[str, ssl.SSLContext], Awaitable[Conn]]


async def _connect(host: str, ctx: ssl.SSLContext) -> Conn:
    return await asyncio.wait_for(asyncio.open_connection(host, RELAY_PORT, ssl=ctx, server_hostname=host,
                                                          ssl_handshake_timeout=DIAL_TIMEOUT), DIAL_TIMEOUT)


class MemberRelayDialer:

    def __init__(self, *, identity: LinkIdentity, rendezvous: Rendezvous, main: Callable[[], Optional[store.LinkRow]],
                 relay_host: Callable[[], Optional[str]], enabled: Callable[[], bool], linked: Callable[[], bool],
                 connect: Connect = _connect, clock: Callable[[], float] = time.monotonic,
                 unlinked_after: float = UNLINKED_SECONDS,
                 roster_shas: Callable[[str], Optional[FrozenSet[str]]] = lambda _iid: None) -> None:
        self._roster_shas = roster_shas
        self._identity, self._rv, self._main, self._relay_host = identity, rendezvous, main, relay_host
        self._enabled, self._linked, self._connect, self._clock, self._after = enabled, linked, connect, clock, unlinked_after
        self._unlinked_since: Optional[float] = None
        self._last_try: Optional[float] = None
        self._task: "Optional[asyncio.Task[None]]" = None

    def tick(self) -> None:
        now = self._clock()
        if self._linked() or not self._enabled():
            self._unlinked_since = None
            return
        if self._unlinked_since is None:
            self._unlinked_since = now
        if now - self._unlinked_since < self._after or (self._last_try is not None and now - self._last_try < self._after):
            return
        if self._task is not None and not self._task.done():
            return
        host, main = self._relay_host(), self._main()
        if host is None or main is None or main.cert_der is None:
            return
        self._last_try = now
        self._task = asyncio.get_running_loop().create_task(self._dial(host, main), name="member-relay-dial")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _dial(self, host: str, main: store.LinkRow) -> None:
        assert main.cert_der is not None
        try:
            pins = pinned_certs([d for d in (main.cert_der, main.next_cert_der) if d], own_link_fid=self._identity.cert.link_fid)
            if not pins:
                return
            ctx = await asyncio.to_thread(client_link_ctx, self._identity, pins)
            ctx.set_alpn_protocols([PACK_ALPN])
            reader, writer = await self._connect(host, ctx)
        except asyncio.CancelledError:
            raise
        except (OSError, ssl.SSLError, asyncio.TimeoutError, ValueError) as exc:
            log.info("member_relay_dial_failed", **failure_fields(exc))
            return
        ssl_obj = writer.get_extra_info("ssl_object")
        der = ssl_obj.getpeercert(binary_form=True) if ssl_obj is not None else None
        sha = hashlib.sha256(der).hexdigest() if der else ""
        listed = self._roster_shas(main.peer_install_id)
        if not der or sha not in {c.cert_sha256 for c in pins} or (listed is not None and sha not in listed) or self._linked():
            writer.close()
            return
        log.info("member_relay_dial_up")
        self._rv.offer(reader, writer, via_relay=True)
