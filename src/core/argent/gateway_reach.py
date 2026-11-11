
from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import os
import re
import shlex
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Protocol
from urllib.parse import urlsplit

import structlog

from src.core.argent import settings as settings_module

logger = structlog.get_logger()

FRESH_SECONDS = 60.0
CARRY_FRESH_SECONDS = 20.0
MAX_HEAD_BYTES = 4096
HEAD_TIMEOUT = 10.0
CONNECT_TIMEOUT = 10.0
MAX_TUNNELS = 64
DIRECT, CARRIED, UNREACHABLE, OFF = "direct", "carried", "unreachable", "off"
_NO_ROUTE = {5, 6, 7, 28}
_NOT_MEASURED = {126, 127}
_NO_ROUTE_VIA = _NO_ROUTE | {56}
_HOST_RE = re.compile(r"[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")
_CONNECT_RE = re.compile(rb"CONNECT ([^ \r\n]+) HTTP/1\.[01]\r\n")
NO_PROXY = "localhost,127.0.0.1,::1"


class ReachError(Exception):
    pass


@dataclass(frozen=True)
class GatewayTarget:

    host: str
    port: int

    def matches(self, authority: str) -> bool:
        host, sep, port = authority.rpartition(":")
        return bool(sep) and port.isdigit() and int(port) == self.port and host.lower().rstrip(".") == self.host


_PRIVATE_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp", ".intranet")


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return host.replace(".", "").isdigit()


def target_of(gateway_url: str) -> GatewayTarget:
    try:
        parts = urlsplit(gateway_url)
        port = parts.port or 443
    except ValueError:
        raise ReachError("gateway address is not usable") from None
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme != "https" or parts.username or parts.password or not host or _HOST_RE.fullmatch(host) is None or port != 443:
        raise ReachError("gateway address cannot be carried")
    if _is_ip_literal(host) or host == "localhost" or host.endswith(_PRIVATE_SUFFIXES) or "." not in host:
        raise ReachError("gateway address must be a public DNS name")
    return GatewayTarget(host, port)


class ConnectProxy:

    def __init__(self, target: GatewayTarget, connect: Optional[Callable[[str, int], Awaitable[Any]]] = None) -> None:
        self._target, self._connect = target, connect or asyncio.open_connection
        self._server: Optional[asyncio.AbstractServer] = None
        self._path = ""
        self._open = 0

    @property
    def path(self) -> str:
        return self._path

    @property
    def target(self) -> GatewayTarget:
        return self._target

    async def start(self, path: str) -> None:
        if self._server is not None:
            return
        folder = os.path.dirname(path)
        try:
            info = os.lstat(folder)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ReachError("the proxy directory is not private")
            with contextlib.suppress(FileNotFoundError):
                if stat.S_ISSOCK(os.lstat(path).st_mode):
                    os.unlink(path)
            self._server = await asyncio.start_unix_server(self._serve, path=path)
            os.chmod(path, 0o600)
        except OSError as exc:
            raise ReachError(f"the proxy socket could not be made ({type(exc).__name__})") from None
        self._path = path

    async def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(server.wait_closed(), 2)
        if self._path:
            with contextlib.suppress(OSError):
                os.unlink(self._path)
            self._path = ""

    @staticmethod
    async def _refuse(writer: asyncio.StreamWriter, code: int) -> None:
        with contextlib.suppress(OSError):
            writer.write(f"HTTP/1.1 {code} refused\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode("ascii"))
            await writer.drain()
        writer.close()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HEAD_TIMEOUT)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, OSError):
            return await self._refuse(writer, 400)
        match = _CONNECT_RE.match(head) if len(head) <= MAX_HEAD_BYTES else None
        if match is None:
            return await self._refuse(writer, 405)
        if not self._target.matches(match.group(1).decode("ascii", "replace")):
            logger.info("argent_carry_refused_host")
            return await self._refuse(writer, 403)
        if self._open >= MAX_TUNNELS:
            return await self._refuse(writer, 503)
        self._open += 1
        try:
            try:
                up_reader, up_writer = await asyncio.wait_for(self._connect(self._target.host, self._target.port), CONNECT_TIMEOUT)
            except (asyncio.TimeoutError, OSError):
                return await self._refuse(writer, 502)
            writer.write(b"HTTP/1.1 200 connection established\r\n\r\n")
            await writer.drain()
            await asyncio.gather(self._pipe(reader, up_writer), self._pipe(up_reader, writer))
        except OSError:
            pass
        finally:
            self._open -= 1
            writer.close()

    @staticmethod
    async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
        try:
            while chunk := await src.read(65536):
                dst.write(chunk)
                await dst.drain()
        except OSError:
            pass
        finally:
            with contextlib.suppress(OSError):
                dst.close()


def exports(port: int) -> str:
    url = shlex.quote(f"http://127.0.0.1:{int(port)}")
    return (f"export HTTPS_PROXY={url} https_proxy={url} NO_PROXY={shlex.quote(NO_PROXY)} no_proxy={shlex.quote(NO_PROXY)}; ")


@dataclass(frozen=True)
class ReachState:

    state: str
    port: int = 0
    reason: str = ""
    checked_at: float = 0.0

    def as_public(self, host_key: str, label: str) -> Dict[str, Any]:
        return {"host_key": host_key, "label": label, "state": self.state, "port": self.port or None, "reason": self.reason, "checked_at": self.checked_at}


class Side(Protocol):

    is_up: bool

    async def run(self, argv: Any = None, *, script: Optional[str] = None, timeout: float = 30.0) -> Any: ...

    async def forward_remote_tcp(self, local_path: str) -> int: ...


def unreachable_reason(label: str) -> str:
    return f"gateway unreachable from {label}"


async def probe_from(side: Side, target: GatewayTarget, via_port: int = 0) -> Optional[bool]:
    proxy = f"-x {shlex.quote(f'http://127.0.0.1:{int(via_port)}')} " if via_port else ""
    script = f"curl -sS -o /dev/null --connect-timeout 5 --max-time 8 {proxy}{shlex.quote(f'https://{target.host}:{target.port}/')}"
    try:
        result = await side.run(script=script, timeout=15.0)
    except Exception as exc:  # noqa: BLE001
        logger.info("argent_reach_probe_failed", error_type=type(exc).__name__)
        return None
    code = getattr(result, "returncode", None)
    if code is None or code in _NOT_MEASURED:
        return None
    return code not in (_NO_ROUTE_VIA if via_port else _NO_ROUTE)


class Reach:

    def __init__(self, *, side_for: Callable[[str], Optional[Side]], label_for: Callable[[str], str], socket_dir: Path, clock: Callable[[], float] = time.time,
                 connect: Optional[Callable[[str, int], Awaitable[Any]]] = None) -> None:
        self.label_for = label_for
        self._side_for, self._label_for, self._dir, self._clock, self._connect = side_for, label_for, socket_dir, clock, connect
        self._states: Dict[str, ReachState] = {}
        self._proxy: Optional[ConnectProxy] = None
        self._lock = asyncio.Lock()

    def state(self, host_key: str) -> Optional[ReachState]:
        return self._states.get(host_key)

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        return {key: st.as_public(key, self._label_for(key)) for key, st in sorted(self._states.items())}

    def exports_for(self, host_key: str) -> str:
        st, side = self._states.get(host_key), self._side_for(host_key)
        fresh = st is not None and self._clock() - st.checked_at < 2 * CARRY_FRESH_SECONDS
        return exports(st.port) if st is not None and st.state == CARRIED and fresh and side is not None and side.is_up else ""

    def reason_for(self, host_key: str) -> str:
        st, side = self._states.get(host_key), self._side_for(host_key)
        if st is None or st.state in (DIRECT, OFF):
            return ""
        if st.state == CARRIED and side is not None and side.is_up:
            return ""
        return unreachable_reason(self._label_for(host_key))

    async def ensure(self, host_key: str, *, force: bool = False) -> ReachState:
        async with self._lock:
            cfg = settings_module.read()
            now = self._clock()
            if not cfg.enabled or not cfg.gateway_url:
                await self._drop_all()
                return self._set(host_key, ReachState(OFF, checked_at=now))
            side, label = self._side_for(host_key), self._label_for(host_key)
            if side is None or not side.is_up:
                return self._set(host_key, ReachState(UNREACHABLE, reason=unreachable_reason(label), checked_at=now))
            prior = self._states.get(host_key)
            window = {DIRECT: FRESH_SECONDS, CARRIED: CARRY_FRESH_SECONDS}.get(prior.state, 0.0) if prior is not None else 0.0
            if not force and prior is not None and now - prior.checked_at < window:
                return prior
            try:
                target = target_of(cfg.gateway_url)
            except ReachError:
                return self._set(host_key, ReachState(UNREACHABLE, reason=unreachable_reason(label), checked_at=now))
            if prior is not None and prior.state == CARRIED and self._proxy is not None and self._proxy.target == target and await probe_from(side, target, prior.port) is True:
                return self._set(host_key, ReachState(CARRIED, port=prior.port, checked_at=now))
            if await probe_from(side, target) is True:
                await self._maybe_close_proxy(exclude=host_key)
                return self._set(host_key, ReachState(DIRECT, checked_at=now))
            try:
                port = await side.forward_remote_tcp(await self._proxy_path(target))
            except Exception as exc:  # noqa: BLE001
                logger.warning("argent_carry_failed", host=host_key, error_type=type(exc).__name__)
                return self._set(host_key, ReachState(UNREACHABLE, reason=unreachable_reason(label), checked_at=now))
            return self._set(host_key, ReachState(CARRIED, port=port, checked_at=now))

    def _set(self, host_key: str, state: ReachState) -> ReachState:
        before = self._states.get(host_key)
        self._states[host_key] = state
        if before is None or (before.state, before.port, before.reason) != (state.state, state.port, state.reason):
            from src.core import resource_push
            from src.core.resource_push import topics

            resource_push.notify(topics.ARGENT_PAIR)
        return state

    async def _proxy_path(self, target: GatewayTarget) -> str:
        if self._proxy is not None and self._proxy.target != target:
            await self._proxy.stop()
            self._proxy = None
        if self._proxy is None:
            self._proxy = ConnectProxy(target, self._connect)
        if not self._proxy.path:
            await self._proxy.start(str(self._dir / "argent-gw.sock"))
        return self._proxy.path

    async def _maybe_close_proxy(self, *, exclude: str) -> None:
        if self._proxy is not None and not any(k != exclude and s.state == CARRIED for k, s in self._states.items()):
            await self._proxy.stop()
            self._proxy = None

    async def _drop_all(self) -> None:
        if self._proxy is not None:
            await self._proxy.stop()
            self._proxy = None
        self._states = {k: ReachState(OFF, checked_at=s.checked_at) for k, s in self._states.items()}

    async def close(self) -> None:
        async with self._lock:
            await self._drop_all()


REACH: Optional[Reach] = None


def get() -> Optional[Reach]:
    return REACH


def set_reach(reach: Optional[Reach]) -> None:
    global REACH
    REACH = reach
