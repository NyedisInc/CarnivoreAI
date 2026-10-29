
from __future__ import annotations

import asyncio
import hashlib
import secrets
import socket
import ssl
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional, Sequence

import structlog

from src.core.computers.link_streams import LocalSocket, inbound_handler
from src.core.computers.mux import frames as f
from src.core.computers.mux.session import MuxError, MuxSession
from src.core.computers.tls_identity import LinkCert, LinkIdentity
from src.core.federation import back_route

log = structlog.get_logger(__name__)

DEFAULT_LINK_PORT = 47110
HANDSHAKE_TIMEOUT = 5.0
HELLO_TIMEOUT = 5.0
PER_SOURCE_HANDSHAKES = 4
TOTAL_HANDSHAKES = 32
MAX_ADDRESSES = 6
FAILURE_LIMIT = 10
FAILURE_WINDOW = 60.0
MAX_TRACKED_SOURCES = 256

STOPPED, DIALING = "stopped", "dialing"
LINKED, ALERTED, NO_HELLO = "linked", "alerted", "no_hello"
ALERT_READ_TIMEOUT = 1.0


def failure_fields(exc: BaseException) -> Dict[str, str]:
    return {"error": type(exc).__name__, "detail": str(exc)[:200]}


class AlertingSSLObject(ssl.SSLObject):
    """An SSL object that keeps the TLS alert OpenSSL queued when a handshake fails, on the exception as ``link_alert``.

    asyncio aborts a failed handshake without flushing that alert, so a TLS 1.3 client (which finishes its side before the server
    checks its certificate) read a plain EOF and could not tell "refused" from a dropped network. ``_TlsGate`` sends the bytes.
    Set it as a context's ``sslobject_class``. Example: ctx.sslobject_class = AlertingSSLObject
    """

    _hook_logged = False

    @classmethod
    def _create(cls, incoming, outgoing, *args, **kwargs):  # noqa: ANN001
        obj = super()._create(incoming, outgoing, *args, **kwargs)
        obj._link_outgoing = outgoing
        return obj

    def do_handshake(self) -> None:
        try:
            super().do_handshake()
        except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
            raise
        except ssl.SSLError as exc:
            outgoing = getattr(self, "_link_outgoing", None)
            if outgoing is None:
                if not AlertingSSLObject._hook_logged:
                    AlertingSSLObject._hook_logged = True
                    log.error("link_alert_hook_missing", error="AttributeError", detail="SSLObject._create no longer sets the outgoing BIO; no TLS alert will be sent")
            else:
                try:
                    exc.link_alert = outgoing.read()  # type: ignore[attr-defined]
                except (ssl.SSLError, ValueError) as read_exc:
                    log.warning("link_alert_read_failed", **failure_fields(read_exc))
            raise


async def _read_alert(reader: asyncio.StreamReader) -> bool:
    try:
        await asyncio.wait_for(reader.read(1), ALERT_READ_TIMEOUT)
    except ssl.SSLError as err:
        return "ALERT" in str(err.reason or "").upper()
    except (OSError, asyncio.TimeoutError, ValueError):
        return False
    return False


@dataclass(frozen=True)
class Member:

    peer_install_id: str
    grant_id: str
    cert: LinkCert
    next_cert: Optional[LinkCert] = None

    def shas(self) -> frozenset:
        return frozenset(c.cert_sha256 for c in (self.cert, self.next_cert) if c is not None)


class _HandshakeGate:

    def __init__(self, per_source: int, total: int, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._per, self._total, self._by_source, self._count = per_source, total, {}, 0
        self._clock = clock
        self._failures: Dict[str, Deque[float]] = {}
        self._inflight: "Dict[object, Callable[[], None]]" = {}

    def track(self, token: object, evict: Callable[[], None]) -> None:
        self._inflight[token] = evict

    def untrack(self, token: object) -> None:
        self._inflight.pop(token, None)

    def evict_oldest(self) -> bool:
        if not self._inflight:
            return False
        token = next(iter(self._inflight))
        self._inflight.pop(token)()
        return True

    def full(self) -> bool:
        return self._count >= self._total

    def _recent(self, source: str) -> int:
        seen = self._failures.get(source)
        if seen is None:
            return 0
        cutoff = self._clock() - FAILURE_WINDOW
        while seen and seen[0] <= cutoff:
            seen.popleft()
        if not seen:
            del self._failures[source]
        return len(seen)

    def note_failure(self, source: str) -> None:
        if source not in self._failures and len(self._failures) >= MAX_TRACKED_SOURCES:
            self._failures.pop(next(iter(self._failures)))
        self._failures.setdefault(source, deque()).append(self._clock())

    def enter(self, source: str) -> bool:
        if self._count >= self._total or self._by_source.get(source, 0) >= self._per or self._recent(source) >= FAILURE_LIMIT:
            return False
        self._by_source[source] = self._by_source.get(source, 0) + 1
        self._count += 1
        return True

    def leave(self, source: str) -> None:
        left = self._by_source.get(source, 0) - 1
        if left > 0:
            self._by_source[source] = left
        else:
            self._by_source.pop(source, None)
        self._count = max(0, self._count - 1)


class _Pending:

    def __init__(self, source: str, conn: socket.socket) -> None:
        self.source: Optional[str] = source
        self.conn = conn
        self.task: "Optional[asyncio.Task[None]]" = None


class _TlsGate:

    def __init__(self, listener: Any, loop: asyncio.AbstractEventLoop, sock: socket.socket) -> None:
        self._listener, self._loop, self._sock = listener, loop, sock
        self._pending: "set[_Pending]" = set()
        self._accepting = loop.create_task(self._accept_loop())

    @classmethod
    async def open(cls, listener: Any, loop: asyncio.AbstractEventLoop, host: str, port: int) -> "_TlsGate":
        sock = socket.create_server((host, port), family=socket.AF_INET6 if ":" in host else socket.AF_INET, backlog=100)
        sock.setblocking(False)
        return cls(listener, loop, sock)

    @property
    def sockets(self) -> "tuple[socket.socket, ...]":
        return (self._sock,)

    def close(self) -> None:
        self._accepting.cancel()
        self._sock.close()
        for pending in list(self._pending):
            self._drop(pending)

    async def wait_closed(self) -> None:
        await asyncio.gather(self._accepting, return_exceptions=True)

    async def _accept_loop(self) -> None:
        while True:
            try:
                conn, peer = await self._loop.sock_accept(self._sock)
            except OSError as exc:
                if self._sock.fileno() == -1:
                    return
                log.warning("link_accept_failed", why=type(exc).__name__)
                await asyncio.sleep(0.1)
                continue
            try:
                self._admit(conn, str(peer[0]) if peer else "?")
            except Exception as exc:  # noqa: BLE001
                log.error("link_admit_failed", **failure_fields(exc))
                conn.close()
            await asyncio.sleep(0)

    def _admit(self, conn: socket.socket, source: str) -> None:
        ctx, gate = self._listener._ctx, self._listener._gate
        if ctx is not None and getattr(self._listener, "EVICT_OLDEST", False) and gate.full():
            gate.evict_oldest()
        if ctx is None or not gate.enter(source):
            log.info("link_handshake_refused", why="cap" if ctx is not None else "no_members")
            conn.close()
            return
        conn.setblocking(False)
        pending = _Pending(source, conn)
        self._pending.add(pending)
        gate.track(pending, lambda: self._evict(pending))
        pending.task = self._loop.create_task(self._handshake(pending, ctx))
        pending.task.add_done_callback(lambda task: task.cancelled() and pending.conn.close())

    def _evict(self, pending: _Pending) -> None:
        log.info("link_handshake_evicted")
        if pending.source is not None:
            self._listener._gate.note_failure(pending.source)
        self._drop(pending)

    def _drop(self, pending: _Pending) -> None:
        self._release(pending)
        if pending.task is not None:
            pending.task.cancel()
        else:
            pending.conn.close()

    def _release(self, pending: _Pending) -> None:
        source, pending.source = pending.source, None
        self._pending.discard(pending)
        self._listener._gate.untrack(pending)
        if source is not None:
            self._listener._gate.leave(source)

    async def _handshake(self, pending: _Pending, ctx: ssl.SSLContext) -> None:
        reader = asyncio.StreamReader(loop=self._loop)
        keep: Optional[socket.socket] = None
        try:
            keep = pending.conn.dup()
            await self._loop.connect_accepted_socket(
                lambda: asyncio.StreamReaderProtocol(reader, self._app, loop=self._loop), pending.conn, ssl=ctx,
                ssl_handshake_timeout=getattr(self._listener, "HANDSHAKE_TIMEOUT", HANDSHAKE_TIMEOUT))
        except (OSError, ssl.SSLError, asyncio.TimeoutError) as exc:
            log.info("link_handshake_failed", **failure_fields(exc))
            alert = getattr(exc, "link_alert", b"")
            if alert and keep is not None:
                try:
                    keep.send(alert)
                except OSError:
                    pass
            if pending.source is not None:
                self._listener._gate.note_failure(pending.source)
            pending.conn.close()
        except asyncio.CancelledError:
            pending.conn.close()
            raise
        finally:
            if keep is not None:
                keep.close()
            self._release(pending)

    async def _app(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await self._listener._on_tls_connection(reader, writer)


@dataclass
class _Conn:

    member: Member
    session: MuxSession
    sha: str


def _member_hello(hello: Dict[str, Any]) -> tuple:
    raw, port = hello.get("addresses"), hello.get("listen_port")
    addresses = [a for a in raw if isinstance(a, str) and 0 < len(a) <= 255 and a.isprintable()][:MAX_ADDRESSES] if isinstance(raw, list) else []
    return addresses, port if isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535 else None


class LinkListener:

    def __init__(self, *, identity: LinkIdentity, fed_dir: Path, listener_path: str, addresses: Callable[[], List[str]],
                 port: int = DEFAULT_LINK_PORT,
                 on_link: Optional[Callable[[str], Awaitable[None]]] = None,
                 on_unlink: Optional[Callable[[str], Awaitable[None]]] = None,
                 on_rotated: Optional[Callable[[str, str], Awaitable[None]]] = None,
                 on_member_hello: Optional[Callable[[str, List[str], Optional[int]], Awaitable[None]]] = None,
                 on_members: Optional[Callable[[Sequence[Member]], None]] = None) -> None:
        self._identity, self._fed_dir, self._listener_path = identity, fed_dir, listener_path
        self._addresses, self.port = addresses, port
        self._on_link, self._on_unlink, self._on_rotated = on_link, on_unlink, on_rotated
        self._on_member_hello, self._on_members = on_member_hello, on_members
        self._members: Dict[str, Member] = {}
        self._by_sha: Dict[str, Member] = {}
        self._conns: Dict[str, _Conn] = {}
        self.state = STOPPED

    def connected(self) -> List[str]:
        return sorted(self._conns)

    async def set_members(self, members: Sequence[Member]) -> str:
        self._members = {m.peer_install_id: m for m in members}
        self._by_sha = {sha: m for m in members for sha in m.shas()}
        self.state = DIALING if members else STOPPED
        if self._on_members is not None:
            self._on_members(list(members))
        for iid, conn in list(self._conns.items()):
            member = self._members.get(iid)
            if member is None or conn.sha not in member.shas():
                await conn.session.close(f.GO_REMOVED)
        return self.state

    async def drop_links(self) -> None:
        for conn in list(self._conns.values()):
            await conn.session.close(f.GO_NORMAL)

    async def stop(self) -> None:
        await self.set_members([])

    async def serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> str:
        try:
            return await self._serve(reader, writer)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("link_connection_failed", **failure_fields(exc))
            return NO_HELLO
        finally:
            writer.close()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> str:
        ssl_obj = writer.get_extra_info("ssl_object")
        try:
            der = ssl_obj.getpeercert(binary_form=True) if ssl_obj is not None else None
        except ValueError:
            return ALERTED if await _read_alert(reader) else NO_HELLO
        member = self._by_sha.get(hashlib.sha256(der).hexdigest()) if der else None
        if member is None:
            return NO_HELLO
        sha = hashlib.sha256(der).hexdigest()
        if member.next_cert is not None and sha == member.next_cert.cert_sha256 and self._on_rotated is not None:
            try:
                await self._on_rotated(member.peer_install_id, sha)
            except Exception as exc:  # noqa: BLE001
                log.error("link_on_rotated_failed", peer=member.peer_install_id[:8], **failure_fields(exc))
                return NO_HELLO
            member = self._by_sha.get(sha)
            if member is None:
                return NO_HELLO
        back_path = str(back_route.socket_dir(self._fed_dir, member.grant_id) / f"in-{member.grant_id}-{secrets.token_hex(back_route.NONCE_HEX // 2)}.sock")
        session = MuxSession(reader, writer, dialer=False, on_open=inbound_handler(self._listener_path))
        local = LocalSocket(session, back_path)
        await local.start()
        conn = _Conn(member, session, sha)
        outcome = NO_HELLO
        try:
            await session.start({"v": f.PROTOCOL_VERSION, "back_path": back_path,
                                 "addresses": list(self._addresses())[:MAX_ADDRESSES], "link_port": self.port})
            try:
                hello = await asyncio.wait_for(session.hello(), HELLO_TIMEOUT)
            except (MuxError, asyncio.TimeoutError):
                err = session.read_error or reader.exception()
                return ALERTED if isinstance(err, ssl.SSLError) and "ALERT" in str(err.reason or "").upper() else NO_HELLO
            if self._by_sha.get(sha) is not member:
                await session.close(f.GO_REMOVED)
                return NO_HELLO
            older = self._conns.get(member.peer_install_id)
            self._conns[member.peer_install_id] = conn
            if older is not None:
                await older.session.close(f.GO_REPLACED)
            if self._on_member_hello is not None:
                addresses, listen_port = _member_hello(hello)
                try:
                    await self._on_member_hello(member.peer_install_id, addresses, listen_port)
                except Exception as exc:  # noqa: BLE001
                    log.error("link_member_hello_failed", peer=member.peer_install_id[:8], **failure_fields(exc))
            if self._on_link is not None:
                try:
                    await self._on_link(member.peer_install_id)
                except Exception as exc:  # noqa: BLE001
                    log.error("link_on_link_failed", peer=member.peer_install_id[:8], **failure_fields(exc))
                    await session.close(f.GO_PROTOCOL)
                    return NO_HELLO
            outcome = LINKED
            await session.wait_closed()
            return outcome
        finally:
            await session.close()
            await local.close()
            if self._conns.get(member.peer_install_id) is conn:
                del self._conns[member.peer_install_id]
                if self._on_unlink is not None:
                    try:
                        await self._on_unlink(member.peer_install_id)
                    except Exception as exc:  # noqa: BLE001
                        log.error("link_on_unlink_failed", **failure_fields(exc))
