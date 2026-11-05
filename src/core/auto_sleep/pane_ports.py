from __future__ import annotations

import asyncio
import ctypes
import ctypes.util
import ipaddress
import socket
import struct
import time
from datetime import datetime
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

import structlog

from src.core.conversation_writers import MeasureError
from src.models.sessions import LocalServerInfo
from src.models.utc_time import utc_now

logger = structlog.get_logger()

__all__ = ["PORT_WATCH", "PortWatch", "Listener", "read_tree_listeners", "parse_socket_fdinfo", "keep_listener"]

TTL_SECONDS: float = 15.0

PORT_MIN, PORT_MAX = 1024, 65535

_PROC_PIDLISTFDS = 1
_PROX_FDTYPE_SOCKET = 2
_PROC_PIDFDSOCKETINFO = 3
_SOCKINFO_TCP = 2
_TSI_S_LISTEN = 1
_INI_IPV4 = 0x1
_FI = 24
_KIND = _FI + 232
_PROTO = _FI + 240
_LPORT, _VFLAG, _LADDR, _STATE = _PROTO + 4, _PROTO + 24, _PROTO + 48, _PROTO + 80
_SOCKET_FDINFO_BUF = 1024

Listener = Tuple[int, str]
NamedListener = Tuple[int, str, Optional[str]]

_lib: Optional[ctypes.CDLL] = None


def _libproc() -> ctypes.CDLL:
    global _lib
    if _lib is None:
        path = ctypes.util.find_library("proc")
        if not path:
            raise MeasureError("libproc is not available on this host")
        try:
            _lib = ctypes.CDLL(path, use_errno=True)
        except OSError as exc:
            raise MeasureError(f"libproc could not load: {type(exc).__name__}") from exc
    return _lib


def parse_socket_fdinfo(raw: bytes) -> Optional[Listener]:
    if len(raw) < _STATE + 4:
        return None
    (kind,) = struct.unpack_from("i", raw, _KIND)
    if kind != _SOCKINFO_TCP:
        return None
    (state,) = struct.unpack_from("i", raw, _STATE)
    if state != _TSI_S_LISTEN:
        return None
    (lport,) = struct.unpack_from("i", raw, _LPORT)
    port = socket.ntohs(lport & 0xFFFF)
    laddr = raw[_LADDR:_LADDR + 16]
    if raw[_VFLAG] & _INI_IPV4:
        address = socket.inet_ntop(socket.AF_INET, laddr[12:16])
    else:
        address = socket.inet_ntop(socket.AF_INET6, laddr)
    return port, address


def keep_listener(listener: Listener) -> bool:
    port, address = listener
    if not PORT_MIN <= port <= PORT_MAX:
        return False
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_unspecified


def _children(lib: ctypes.CDLL, pid: int) -> List[int]:
    count = lib.proc_listchildpids(pid, None, 0)
    if count <= 0:
        return []
    buf = (ctypes.c_int * (count + 64))()
    got = lib.proc_listchildpids(pid, buf, ctypes.sizeof(buf))
    return [buf[i] for i in range(max(got, 0)) if buf[i] > 0]


def _pid_listeners(lib: ctypes.CDLL, pid: int) -> List[Listener]:
    need = lib.proc_pidinfo(pid, _PROC_PIDLISTFDS, 0, None, 0)
    if need <= 0:
        return []
    fds = ctypes.create_string_buffer(need + 32 * 8)
    got = lib.proc_pidinfo(pid, _PROC_PIDLISTFDS, 0, fds, len(fds))
    found: List[Listener] = []
    info = ctypes.create_string_buffer(_SOCKET_FDINFO_BUF)
    for off in range(0, max(got, 0) - 7, 8):
        fd, fdtype = struct.unpack_from("iI", fds.raw, off)
        if fdtype != _PROX_FDTYPE_SOCKET:
            continue
        if lib.proc_pidfdinfo(pid, fd, _PROC_PIDFDSOCKETINFO, info, len(info)) <= 0:
            continue
        listener = parse_socket_fdinfo(info.raw)
        if listener is not None and keep_listener(listener):
            found.append(listener)
    return found


def _proc_name(lib: ctypes.CDLL, pid: int) -> Optional[str]:
    buf = ctypes.create_string_buffer(256)
    got = lib.proc_name(pid, buf, ctypes.sizeof(buf))
    if got <= 0:
        return None
    return buf.value.decode("utf-8", "replace") or None


def read_tree_listeners(pane_pids: Iterable[int]) -> Dict[int, List[NamedListener]]:
    lib = _libproc()
    out: Dict[int, List[NamedListener]] = {}
    for pane in pane_pids:
        by_port: Dict[int, Tuple[str, Optional[str]]] = {}
        seen: Set[int] = {pane}
        stack = _children(lib, pane)
        while stack:
            pid = stack.pop()
            if pid in seen:
                continue
            seen.add(pid)
            stack.extend(_children(lib, pid))
            for port, address in _pid_listeners(lib, pid):
                if port not in by_port or ipaddress.ip_address(address).is_unspecified:
                    by_port[port] = (address, _proc_name(lib, pid))
        out[pane] = sorted((port, address, name) for port, (address, name) in by_port.items())
    return out


class PortWatch:

    def __init__(self, read: Callable[[Iterable[int]], Dict[int, List[NamedListener]]] = read_tree_listeners,
                 ttl: float = TTL_SECONDS, clock: Callable[[], float] = time.monotonic) -> None:
        self._read = read
        self._ttl = ttl
        self._clock = clock
        self._wanted: Set[int] = set()
        self._ports: Dict[int, List[LocalServerInfo]] = {}
        self._read_at: Optional[float] = None
        self._task: Optional["asyncio.Task[None]"] = None
        self.reads = 0

    def servers(self, pane_pid: Optional[int]) -> List[LocalServerInfo]:
        if not pane_pid:
            return []
        self._wanted.add(pane_pid)
        return list(self._ports.get(pane_pid, ()))

    def invalidate(self) -> None:
        self._read_at = None

    def tick(self, wake: Callable[[], None]) -> None:
        if not self._wanted or (self._task is not None and not self._task.done()):
            return
        now = self._clock()
        if self._read_at is not None and now - self._read_at < self._ttl:
            return
        self._read_at = now
        wanted, self._wanted = self._wanted, set()
        self._task = asyncio.get_running_loop().create_task(self._refresh(wanted, wake))

    async def _refresh(self, panes: Set[int], wake: Callable[[], None]) -> None:
        self.reads += 1
        try:
            fresh = await asyncio.to_thread(self._read, panes)
        except (MeasureError, OSError) as exc:
            logger.warning("pane_ports_read_failed", error=str(exc), error_type=type(exc).__name__)
            return
        if self.commit(panes, fresh):
            wake()

    def commit(self, panes: Set[int], fresh: Dict[int, List[NamedListener]]) -> bool:
        moved = False
        for gone in [p for p in self._ports if p not in panes]:
            del self._ports[gone]
        for pane in panes:
            old = {(s.port, s.address): s for s in self._ports.get(pane, ())}
            stamp: datetime = utc_now()
            new = [old.get((entry[0], entry[1])) or LocalServerInfo(
                       port=entry[0], address=entry[1], process=entry[2] if len(entry) > 2 else None,
                       url=f"http://localhost:{entry[0]}", first_seen=stamp, last_seen=stamp)
                   for entry in fresh.get(pane, [])]
            if [(s.port, s.address) for s in new] != list(old):
                moved = True
            if new:
                self._ports[pane] = new
            else:
                self._ports.pop(pane, None)
        return moved


PORT_WATCH = PortWatch()
