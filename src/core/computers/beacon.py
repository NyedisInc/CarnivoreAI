
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import socket
import time
from collections import deque
from typing import Callable, Deque, Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.computers.link_listener import Member

log = structlog.get_logger(__name__)

BEACON_UDP_PORT = 47120
BEACON_FALLBACK_PORT = 29120
MAGIC = b"CCPB"
VERSION = 1
HINT_BYTES = 8
PACKET_SIZE = len(MAGIC) + 1 + HINT_BYTES
BROADCAST = "255.255.255.255"
BURST_SENDS, BURST_GAP, STEADY_GAP, IDLE_POLL = 3, 2.0, 60.0, 15.0
KICK_PER_MEMBER_SECONDS, KICKS_PER_MINUTE = 10.0, 6
MALFORMED_LOG_SECONDS = 60.0
_RFC1918 = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))

Send = Callable[[str, bytes], None]


def rfc1918(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.version == 4 and any(ip in net for net in _RFC1918)


def subnet_of(address: str) -> Optional[str]:
    return str(ipaddress.ip_network(f"{address}/24", strict=False)) if rfc1918(address) else None


def day_number(now: float) -> int:
    return int(now // 86400)


def hint_for(cert_sha256: str, day: int) -> bytes:
    return hashlib.sha256(bytes.fromhex(cert_sha256) + day.to_bytes(8, "big")).digest()[:HINT_BYTES]


def encode(cert_sha256: str, now: float) -> bytes:
    return MAGIC + bytes([VERSION]) + hint_for(cert_sha256, day_number(now))


def parse(data: bytes) -> Optional[bytes]:
    if len(data) != PACKET_SIZE or data[:len(MAGIC)] != MAGIC or data[len(MAGIC)] != VERSION:
        return None
    return data[len(MAGIC) + 1:]


def hint_table(members: Sequence[Member], now: float) -> Dict[bytes, str]:
    day = day_number(now)
    return {hint_for(sha, d): m.peer_install_id for m in members for sha in sorted(m.shas()) for d in (day - 1, day, day + 1)}


class KickThrottle:

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._last: Dict[str, float] = {}
        self._recent: Deque[float] = deque()

    def allow(self, iid: str) -> bool:
        now = self._clock()
        while self._recent and now - self._recent[0] >= 60.0:
            self._recent.popleft()
        if len(self._recent) >= KICKS_PER_MINUTE or now - self._last.get(iid, -KICK_PER_MEMBER_SECONDS) < KICK_PER_MEMBER_SECONDS:
            return False
        self._last[iid] = now
        self._recent.append(now)
        return True

    def refund(self, iid: str) -> None:
        if self._last.pop(iid, None) is not None and self._recent:
            self._recent.pop()


class _Protocol(asyncio.DatagramProtocol):

    def __init__(self, owner: "BeaconListener") -> None:
        self._owner = owner

    def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:  # noqa: D102
        self._owner.handle(data, str(addr[0]))

    def error_received(self, exc: Exception) -> None:  # noqa: D102
        log.info("pack_beacon_socket_error", error_type=type(exc).__name__)


class BeaconListener:

    def __init__(self, *, members: Callable[[], Sequence[Member]], connected: Callable[[], Sequence[str]],
                 kick: Callable[[str, str], None], host: str, port: int = BEACON_UDP_PORT,
                 fallback_port: Optional[int] = BEACON_FALLBACK_PORT, clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time) -> None:
        self._members, self._connected, self._kick, self._host, self._port = members, connected, kick, host, port
        self._fallback_port = fallback_port
        self.bound_port: Optional[int] = None
        self._clock, self._wall = clock, wall
        self.throttle = KickThrottle(clock)
        self.last_heard: Optional[float] = None
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._table_key: Optional[Tuple] = None
        self._table: Dict[bytes, str] = {}
        self._malformed_logged: Optional[float] = None

    @property
    def running(self) -> bool:
        return self._transport is not None

    async def start(self) -> bool:
        if self._transport is not None:
            return True
        loop = asyncio.get_running_loop()
        for port in (self._port, self._fallback_port):
            if port is None:
                continue
            try:
                self._transport, _ = await loop.create_datagram_endpoint(
                    lambda: _Protocol(self), local_addr=(self._host, port), reuse_port=True if hasattr(socket, "SO_REUSEPORT") else None)
            except OSError as exc:
                log.warning("pack_beacon_bind_failed", port=port, error_type=type(exc).__name__)
                continue
            self.bound_port = self._transport.get_extra_info("sockname")[1]
            log.info("pack_beacon_listening", port=self.bound_port, fallback=port != self._port)
            return True
        return False

    async def stop(self) -> None:
        transport, self._transport, self.bound_port = self._transport, None, None
        if transport is not None:
            transport.close()

    def _hints(self) -> Dict[bytes, str]:
        members = list(self._members())
        now = self._wall()
        key = (day_number(now), tuple(sorted((m.peer_install_id, tuple(sorted(m.shas()))) for m in members)))
        if key != self._table_key:
            self._table_key, self._table = key, hint_table(members, now)
        return self._table

    def handle(self, data: bytes, source: str) -> str:
        hint = parse(data)
        if hint is None:
            now = self._clock()
            if self._malformed_logged is None or now - self._malformed_logged >= MALFORMED_LOG_SECONDS:
                self._malformed_logged = now
                log.info("pack_beacon_malformed")
            return "malformed"
        if not rfc1918(source):
            return "not_lan"
        iid = self._hints().get(hint)
        if iid is None:
            return "unknown"
        self.last_heard = self._wall()
        if iid in self._connected():
            return "connected"
        if not self.throttle.allow(iid):
            return "throttled"
        self._kick(iid, source)
        return "kicked"


class BeaconSender:

    def __init__(self, *, cert_sha256: Callable[[], str], addresses: Callable[[], List[str]], subnets: Callable[[], List[str]],
                 linked: Callable[[], bool], enabled: Callable[[], bool], port: int = BEACON_UDP_PORT,
                 fallback_port: Optional[int] = BEACON_FALLBACK_PORT, send: Optional[Send] = None, wall: Callable[[], float] = time.time) -> None:
        self._sha, self._addresses, self._subnets, self._linked, self._enabled = cert_sha256, addresses, subnets, linked, enabled
        self._ports = tuple(p for p in (port, fallback_port) if p is not None)
        self._send, self._wall = send or self._broadcast, wall
        self._seen: Optional[List[str]] = None
        self._burst = 0
        self._was_linked = False
        self._task: "Optional[asyncio.Task[None]]" = None

    def eligible(self) -> List[str]:
        nets = []
        for text in self._subnets():
            try:
                nets.append(ipaddress.ip_network(text, strict=False))
            except ValueError:
                continue
        return [a for a in self._addresses() if rfc1918(a) and any(ipaddress.ip_address(a) in n for n in nets)]

    def _broadcast(self, address: str, packet: bytes) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(0.5)
            sock.bind((address, 0))
            failure: Optional[OSError] = None
            sent = False
            for port in self._ports:
                try:
                    sock.sendto(packet, (BROADCAST, port))
                    sent = True
                except OSError as exc:
                    failure = exc
            if not sent and failure is not None:
                raise failure

    def step(self) -> float:
        if not self._enabled():
            return IDLE_POLL
        if self._linked():
            self._was_linked = True
            return IDLE_POLL
        addresses = self.eligible()
        if self._was_linked or addresses != self._seen:
            self._was_linked, self._seen, self._burst = False, addresses, BURST_SENDS
        if not addresses:
            return IDLE_POLL
        packet = encode(self._sha(), self._wall())
        for address in addresses:
            try:
                self._send(address, packet)
            except OSError as exc:
                log.info("pack_beacon_send_failed", error_type=type(exc).__name__)
        self._burst = max(0, self._burst - 1)
        return BURST_GAP if self._burst > 0 else STEADY_GAP

    async def _run(self) -> None:
        while True:
            try:
                delay = self.step()
            except asyncio.CancelledError:
                raise
            except (ValueError, RuntimeError) as exc:
                log.warning("pack_beacon_step_failed", error_type=type(exc).__name__)
                delay = IDLE_POLL
            await asyncio.sleep(delay)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run(), name="pack-beacon-sender")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
