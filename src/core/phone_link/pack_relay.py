
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import ssl
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence

import structlog

from src.core.computers.link_listener import LinkListener, _HandshakeGate, _TlsGate, failure_fields
from src.core.computers.tls_identity import LinkCert, LinkIdentity, server_link_ctx
from src.core.pack.reconnect import config as reconnect_config
from src.core.phone_link.gate import LinkStream, StreamTable

log = structlog.get_logger(__name__)

PACK_ALPN = "carnivore-pack/1"
PEEK_SECONDS = 2.0
HANDSHAKE_SECONDS = 2.0
PER_IP_HANDSHAKES = 4
TOTAL_HANDSHAKES = 16
MAX_PACK_STREAMS = 8
RELAY_DAILY_CAP = 5 * 1024 ** 3
PACK_SHARE = 0.5
PERSIST_EVERY = 4 * 1024 * 1024


class PackAdmission:

    def __init__(self, per_source: int = PER_IP_HANDSHAKES, total: int = TOTAL_HANDSHAKES) -> None:
        self._gate = _HandshakeGate(per_source, total)

    def enter(self, info: LinkStream) -> bool:
        if info.slot or not self._gate.enter(info.client_ip):
            return False
        info.slot = True
        return True

    def release(self, info: LinkStream, *, failed: bool = False) -> None:
        if not info.slot:
            return
        info.slot = False
        self._gate.leave(info.client_ip)
        if failed:
            self._gate.note_failure(info.client_ip)


class RelayBudget:

    def __init__(self, path: Path, *, on_exhausted: Optional[Callable[[], None]] = None, clock: Callable[[], float] = time.time,
                 limit: int = int(RELAY_DAILY_CAP * PACK_SHARE)) -> None:
        self._path, self._on_exhausted, self._clock, self.limit = Path(path), on_exhausted, clock, limit
        self._day, self._bytes, self._saved = self._load()
        self._told = self._bytes >= self.limit

    def _today(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(self._clock()))

    def _load(self) -> "tuple[str, int, int]":
        today = self._today()
        try:
            data = json.loads(self._path.read_text())
            if data.get("day") == today and isinstance(data.get("bytes"), int) and not isinstance(data.get("bytes"), bool) and data["bytes"] >= 0:
                return today, data["bytes"], data["bytes"]
        except (OSError, ValueError, AttributeError):
            pass
        return today, 0, 0

    def _roll(self) -> None:
        today = self._today()
        if today != self._day:
            self._day, self._bytes, self._saved, self._told = today, 0, 0, False

    @property
    def used(self) -> int:
        self._roll()
        return self._bytes

    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit

    def add(self, count: int) -> None:
        self._roll()
        self._bytes += max(0, count)
        crossed = self._bytes >= self.limit and not self._told
        if crossed:
            self._told = True
        if crossed or self._bytes - self._saved >= PERSIST_EVERY:
            self.flush()
        if crossed:
            log.warning("pack_relay_budget_used", used=self._bytes)
            if self._on_exhausted is not None:
                self._on_exhausted()

    def flush(self) -> None:
        payload = json.dumps({"day": self._day, "bytes": self._bytes})
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".relay-budget-")
            try:
                with os.fdopen(fd, "w") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, self._path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            self._saved = self._bytes
        except OSError as exc:
            log.warning("pack_relay_budget_save_failed", **failure_fields(exc))


class _OpenGate:

    def enter(self, source: str) -> bool:
        return True

    def leave(self, source: str) -> None:
        pass

    def note_failure(self, source: str) -> None:
        pass

    def track(self, token: object, evict: Callable[[], None]) -> None:
        pass

    def untrack(self, token: object) -> None:
        pass

    def full(self) -> bool:
        return False


class PackAcceptor:

    HANDSHAKE_TIMEOUT = HANDSHAKE_SECONDS

    def __init__(self, *, identity: LinkIdentity, hub: LinkListener, admission: PackAdmission, table: StreamTable) -> None:
        self._identity, self._hub, self._admission, self.table = identity, hub, admission, table
        self._gate = _OpenGate()
        self._ctx: Optional[ssl.SSLContext] = None
        self._shas: frozenset = frozenset()
        self._server: Optional[Any] = None
        self.port: Optional[int] = None
        self.send_trust: Optional[Callable[[int], None]] = None

    async def start(self) -> None:
        if self._server is None:
            self._server = await _TlsGate.open(self, asyncio.get_running_loop(), "127.0.0.1", 0)
            self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        server, self._server, self.port = self._server, None, None
        if server is not None:
            server.close()

    async def set_pins(self, pins: Sequence[LinkCert]) -> None:
        ctx = await asyncio.to_thread(server_link_ctx, self._identity, pins) if pins else None
        if ctx is not None:
            ctx.set_alpn_protocols([PACK_ALPN])
        self._ctx = ctx
        self._shas = frozenset(c.cert_sha256 for c in pins)

    async def _on_tls_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        ssl_obj = writer.get_extra_info("ssl_object")
        der = ssl_obj.getpeercert(binary_form=True) if ssl_obj is not None else None
        peer = writer.get_extra_info("peername")
        info = self.table.lookup(peer[1]) if peer else None
        if info is not None:
            self._admission.release(info)
        if not der or hashlib.sha256(der).hexdigest() not in self._shas or info is None:
            log.info("pack_relay_handshake_failed", why="not_pinned" if info is not None else "not_from_the_tunnel")
            writer.close()
            return
        if self.send_trust is not None:
            self.send_trust(info.stream_id)
        info.trusted = True
        await self._hub.serve(reader, writer, relayed=True)


class PackRelay:

    max_streams = MAX_PACK_STREAMS

    def __init__(self, *, identity: LinkIdentity, hub: LinkListener, config_path: Path, budget_path: Path) -> None:
        self._config_path = Path(config_path)
        self.table = StreamTable()
        self.admission = PackAdmission()
        self.budget = RelayBudget(budget_path, on_exhausted=hub.reset_relayed_streams)
        self.acceptor = PackAcceptor(identity=identity, hub=hub, admission=self.admission, table=self.table)
        self.members = 0

    def use_table(self, table: StreamTable) -> None:
        self.table = self.acceptor.table = table

    def enabled(self) -> bool:
        return reconnect_config.relay_on(self._config_path)

    def wanted(self) -> bool:
        return self.members > 0 and self.enabled()

    def port(self) -> Optional[int]:
        return self.acceptor.port

    async def set_members(self, members: Sequence[Any]) -> bool:
        pins = [c for m in members for c in (m.cert, m.next_cert) if c is not None]
        await self.acceptor.set_pins(pins)
        changed, self.members = (self.members > 0) != (len(members) > 0), len(members)
        return changed

    async def stop(self) -> None:
        await self.acceptor.stop()
        self.budget.flush()
