
from __future__ import annotations

import ctypes
import ctypes.util
import struct
import sys
import threading
import time
from typing import Dict, Iterable, List, NamedTuple, Optional, Tuple

import structlog

logger = structlog.get_logger()

_PROC_PIDTBSDINFO = 3
_PROC_PIDTASKINFO = 4
_PROC_PIDT_SHORTBSDINFO = 13
_PROC_PIDVNODEPATHINFO = 9
_MAXPATHLEN = 1024
_VNODEPATHINFO_SIZE = 2352
_VNODE_PATH_OFFSET = 152
_CTL_KERN, _KERN_PROC, _KERN_PROC_PID, _KERN_PROCARGS2 = 1, 14, 1, 49
_ARGV_RECHECK_SECONDS = 12.0
_YOUNG_SECONDS = 10.0
_PATH_MAX_BUF = 4096


class _BsdInfo(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint32), ("status", ctypes.c_uint32), ("xstatus", ctypes.c_uint32),
                ("pid", ctypes.c_uint32), ("ppid", ctypes.c_uint32), ("uid", ctypes.c_uint32),
                ("gid", ctypes.c_uint32), ("ruid", ctypes.c_uint32), ("rgid", ctypes.c_uint32),
                ("svuid", ctypes.c_uint32), ("svgid", ctypes.c_uint32), ("rfu_1", ctypes.c_uint32),
                ("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32),
                ("nfiles", ctypes.c_uint32), ("pgid", ctypes.c_uint32), ("pjobc", ctypes.c_uint32),
                ("e_tdev", ctypes.c_uint32), ("e_tpgid", ctypes.c_uint32), ("nice", ctypes.c_int32),
                ("start_sec", ctypes.c_uint64), ("start_usec", ctypes.c_uint64)]


class _ShortInfo(ctypes.Structure):

    _fields_ = [("pid", ctypes.c_uint32), ("ppid", ctypes.c_uint32), ("pgid", ctypes.c_uint32),
                ("status", ctypes.c_uint32), ("comm", ctypes.c_char * 16), ("flags", ctypes.c_uint32),
                ("uid", ctypes.c_uint32), ("gid", ctypes.c_uint32), ("ruid", ctypes.c_uint32),
                ("rgid", ctypes.c_uint32), ("svuid", ctypes.c_uint32), ("svgid", ctypes.c_uint32),
                ("rfu", ctypes.c_uint32)]


class _TaskInfo(ctypes.Structure):
    _fields_ = [("virtual_size", ctypes.c_uint64), ("resident_size", ctypes.c_uint64),
                ("total_user", ctypes.c_uint64), ("total_system", ctypes.c_uint64),
                ("threads_user", ctypes.c_uint64), ("threads_system", ctypes.c_uint64),
                ("policy", ctypes.c_int32), ("faults", ctypes.c_int32), ("pageins", ctypes.c_int32),
                ("cow_faults", ctypes.c_int32), ("messages_sent", ctypes.c_int32),
                ("messages_received", ctypes.c_int32), ("syscalls_mach", ctypes.c_int32),
                ("syscalls_unix", ctypes.c_int32), ("csw", ctypes.c_int32), ("threadnum", ctypes.c_int32),
                ("numrunning", ctypes.c_int32), ("priority", ctypes.c_int32)]


class _Timebase(ctypes.Structure):
    _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]


class SnapRow(NamedTuple):

    pid: int
    ppid: int
    uid: int
    start: Tuple[int, int]
    command: str

    @property
    def lstart(self) -> str:
        return " ".join(time.ctime(self.start[0]).split()) if self.start[0] else ""


_lock = threading.Lock()
_libc = None
_libc_failed = False
_argmax = 0
_argbuf = None
_argv_cache: Dict[Tuple[int, int, int, bytes], Tuple[str, float]] = {}
_start_cache: Dict[int, Tuple[int, bytes, Tuple[int, int]]] = {}
_snap: Optional[List[SnapRow]] = None
_snap_at: float = -1e9


def _load():
    global _libc, _libc_failed, _argmax, _argbuf
    if _libc is not None or _libc_failed:
        return _libc
    try:
        if sys.platform != "darwin":
            raise OSError("libproc is macOS only")
        lib = ctypes.CDLL(ctypes.util.find_library("c") or "/usr/lib/libSystem.B.dylib", use_errno=True)
        lib.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        lib.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        lib.sysctl.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_uint, ctypes.c_void_p,
                               ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t]
        size = ctypes.c_int(0)
        sz = ctypes.c_size_t(ctypes.sizeof(size))
        if lib.sysctlbyname(b"kern.argmax", ctypes.byref(size), ctypes.byref(sz), None, 0) != 0 or size.value <= 0:
            raise OSError("kern.argmax unreadable")
        _argmax = size.value
        _argbuf = ctypes.create_string_buffer(_argmax)
        _libc = lib
    except (OSError, AttributeError) as exc:
        _libc_failed = True
        logger.warning("libproc_unavailable", error=str(exc))
    return _libc


def _bsdinfo(lib, pid: int) -> Optional[_BsdInfo]:
    info = _BsdInfo()
    got = lib.proc_pidinfo(pid, _PROC_PIDTBSDINFO, 0, ctypes.byref(info), ctypes.sizeof(info))
    return info if got == ctypes.sizeof(info) and info.pid == pid else None


def _shortinfo(lib, pid: int) -> Optional[_ShortInfo]:
    info = _ShortInfo()
    got = lib.proc_pidinfo(pid, _PROC_PIDT_SHORTBSDINFO, 0, ctypes.byref(info), ctypes.sizeof(info))
    return info if got == ctypes.sizeof(info) and info.pid == pid else None


def _proc_start(lib, pid: int) -> Optional[Tuple[int, int]]:
    buf = ctypes.create_string_buffer(1024)
    size = ctypes.c_size_t(ctypes.sizeof(buf))
    mib = (ctypes.c_int * 4)(_CTL_KERN, _KERN_PROC, _KERN_PROC_PID, pid)
    if lib.sysctl(mib, 4, buf, ctypes.byref(size), None, 0) != 0 or size.value < 16:
        return None
    sec, usec = struct.unpack_from("=qi", buf.raw)
    return (sec, usec) if sec > 0 else None


def _argv_list(lib, pid: int) -> Optional[List[str]]:
    mib = (ctypes.c_int * 3)(_CTL_KERN, _KERN_PROCARGS2, pid)
    size = ctypes.c_size_t(_argmax)
    if lib.sysctl(mib, 3, _argbuf, ctypes.byref(size), None, 0) != 0 or size.value < 4:
        return None
    raw = ctypes.string_at(_argbuf, size.value)
    argc = int.from_bytes(raw[:4], "little")
    parts = raw[4:].split(b"\0", argc + 64)
    i = 1
    while i < len(parts) and parts[i] == b"":
        i += 1
    args = [p.decode("utf-8", errors="replace") for p in parts[i:i + argc]]
    return args or None


def _argv(lib, pid: int) -> Optional[str]:
    args = _argv_list(lib, pid)
    return " ".join(args).rstrip() if args else None


def _cwd(lib, pid: int) -> Optional[str]:
    buf = ctypes.create_string_buffer(_VNODEPATHINFO_SIZE)
    got = lib.proc_pidinfo(pid, _PROC_PIDVNODEPATHINFO, 0, buf, _VNODEPATHINFO_SIZE)
    if got != _VNODEPATHINFO_SIZE:
        return None
    path = buf.raw[_VNODE_PATH_OFFSET:_VNODE_PATH_OFFSET + _MAXPATHLEN].split(b"\0", 1)[0]
    return path.decode("utf-8", errors="replace") or None


class ProcDetail(NamedTuple):

    start: Tuple[int, int]
    argv: Tuple[str, ...]
    cwd: Optional[str]


def process_details(pids: Iterable[int]) -> Optional[Dict[int, ProcDetail]]:
    with _lock:
        lib = _load()
        if lib is None:
            return None
        out: Dict[int, ProcDetail] = {}
        for pid in {int(p) for p in pids}:
            info = _bsdinfo(lib, pid)
            args = _argv_list(lib, pid) if info is not None else None
            if info is None or args is None:
                continue
            out[pid] = ProcDetail((info.start_sec, info.start_usec), tuple(args), _cwd(lib, pid))
        return out


def _fallback_command(lib, pid: int, name: bytes) -> str:
    buf = ctypes.create_string_buffer(_PATH_MAX_BUF)
    if lib.proc_pidpath(pid, buf, _PATH_MAX_BUF) > 0 and buf.value:
        return buf.value.decode("utf-8", errors="replace")
    return name.decode("utf-8", errors="replace")


def _take() -> Optional[List[SnapRow]]:
    lib = _load()
    if lib is None:
        return None
    count = lib.proc_listallpids(None, 0)
    if count <= 0:
        return None
    cap = count + 64
    pids = (ctypes.c_int * cap)()
    n = lib.proc_listallpids(pids, ctypes.sizeof(pids))
    if n <= 0:
        return None
    rows: List[SnapRow] = []
    live_starts: Dict[int, Tuple[int, bytes, Tuple[int, int]]] = {}
    live_argv: Dict[Tuple[int, int, int, bytes], Tuple[str, float]] = {}
    now, wall = time.monotonic(), time.time()
    for pid in pids[:n]:
        if pid < 0:
            continue
        info = _bsdinfo(lib, pid)
        if info is None:
            short = _shortinfo(lib, pid)
            if short is None:
                continue
            uid, ppid, name = short.uid, short.ppid, short.comm
            seen = _start_cache.get(pid)
            start = seen[2] if seen is not None and seen[:2] == (ppid, name) else (_proc_start(lib, pid) or (0, 0))
            live_starts[pid] = (ppid, name, start)
            command = _fallback_command(lib, pid, name)
        else:
            start, uid, ppid, name = (info.start_sec, info.start_usec), info.uid, info.ppid, info.name or info.comm
            key = (pid, start[0], start[1], name)
            cached = _argv_cache.get(key) if wall - start[0] >= _YOUNG_SECONDS else None
            if cached is not None and now - cached[1] < _ARGV_RECHECK_SECONDS + pid % 8:
                command, read_at = cached
            else:
                command, read_at = _argv(lib, pid) or _fallback_command(lib, pid, name), now
            live_argv[key] = (command, read_at)
        rows.append(SnapRow(pid, ppid, uid, start, command))
    _argv_cache.clear()
    _argv_cache.update(live_argv)
    _start_cache.clear()
    _start_cache.update(live_starts)
    return rows or None


def snapshot(max_age: float = 0.0) -> Optional[List[SnapRow]]:
    global _snap, _snap_at
    with _lock:
        if max_age > 0 and _snap is not None and time.monotonic() - _snap_at < max_age:
            return _snap
        try:
            rows = _take()
        except (OSError, ValueError, ctypes.ArgumentError) as exc:
            logger.warning("libproc_snapshot_failed", error=str(exc), error_type=type(exc).__name__)
            return None
        if rows is not None:
            _snap, _snap_at = rows, time.monotonic()
        return rows


def start_text(pids) -> Optional[Dict[int, str]]:
    with _lock:
        lib = _load()
        if lib is None:
            return None
        out: Dict[int, str] = {}
        for pid in {int(p) for p in pids}:
            info = _bsdinfo(lib, pid)
            start = (info.start_sec, 0) if info is not None else _proc_start(lib, pid)
            if start is not None:
                out[pid] = time.ctime(start[0])
        return out


class TaskRow(NamedTuple):
    pid: int
    ppid: int
    cpu_ns: int
    rss_kb: int


def task_table() -> Optional[List[TaskRow]]:
    with _lock:
        lib = _load()
        if lib is None:
            return None
        tb = _Timebase()
        if lib.mach_timebase_info(ctypes.byref(tb)) != 0 or tb.denom == 0:
            return None
        count = lib.proc_listallpids(None, 0)
        if count <= 0:
            return None
        pids = (ctypes.c_int * (count + 64))()
        n = lib.proc_listallpids(pids, ctypes.sizeof(pids))
        out: List[TaskRow] = []
        for pid in pids[:max(n, 0)]:
            if pid <= 0:
                continue
            info = _shortinfo(lib, pid)
            if info is None:
                continue
            task = _TaskInfo()
            got = lib.proc_pidinfo(pid, _PROC_PIDTASKINFO, 0, ctypes.byref(task), ctypes.sizeof(task))
            if got == ctypes.sizeof(task):
                ticks = task.total_user + task.total_system
                out.append(TaskRow(pid, info.ppid, ticks * tb.numer // tb.denom, task.resident_size // 1024))
            else:
                out.append(TaskRow(pid, info.ppid, 0, 0))
        return out
