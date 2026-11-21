
from __future__ import annotations

import ctypes
import ctypes.util
import errno
import sys
from typing import Callable, NamedTuple, Optional, Tuple

PROC_PIDTASKINFO = 4
LIBPROC_FALLBACK_PATH = "/usr/lib/libproc.dylib"
NANOSECONDS_PER_SECOND = 1_000_000_000


class ProcTaskInfo(ctypes.Structure):

    _fields_ = [
        ("pti_virtual_size", ctypes.c_uint64),
        ("pti_resident_size", ctypes.c_uint64),
        ("pti_total_user", ctypes.c_uint64),
        ("pti_total_system", ctypes.c_uint64),
        ("pti_threads_user", ctypes.c_uint64),
        ("pti_threads_system", ctypes.c_uint64),
        ("pti_policy", ctypes.c_int32),
        ("pti_faults", ctypes.c_int32),
        ("pti_pageins", ctypes.c_int32),
        ("pti_cow_faults", ctypes.c_int32),
        ("pti_messages_sent", ctypes.c_int32),
        ("pti_messages_received", ctypes.c_int32),
        ("pti_syscalls_mach", ctypes.c_int32),
        ("pti_syscalls_unix", ctypes.c_int32),
        ("pti_csw", ctypes.c_int32),
        ("pti_threadnum", ctypes.c_int32),
        ("pti_numrunning", ctypes.c_int32),
        ("pti_priority", ctypes.c_int32),
    ]


class _TimebaseInfo(ctypes.Structure):

    _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]


class ProcessGone(Exception):
    pass


class RawUsage(NamedTuple):

    rss_bytes: int
    cpu_seconds: float


def mach_to_seconds(ticks: int, numer: int, denom: int) -> float:
    return ticks * numer / denom / NANOSECONDS_PER_SECOND


def _load_libproc() -> Optional[ctypes.CDLL]:
    if sys.platform != "darwin":
        return None
    for path in (ctypes.util.find_library("proc"), LIBPROC_FALLBACK_PATH):
        if not path:
            continue
        try:
            lib = ctypes.CDLL(path, use_errno=True)
            lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
            lib.proc_pidinfo.restype = ctypes.c_int
            return lib
        except (OSError, AttributeError):
            continue
    return None


def _load_timebase() -> Optional[Tuple[int, int]]:
    try:
        lib = ctypes.CDLL(None)
        info = _TimebaseInfo()
        if lib.mach_timebase_info(ctypes.byref(info)) != 0 or info.denom == 0:
            return None
        return info.numer, info.denom
    except (OSError, AttributeError):
        return None


_LIBPROC = _load_libproc()
_TIMEBASE = _load_timebase() if _LIBPROC is not None else None


def available() -> bool:
    return _LIBPROC is not None and _TIMEBASE is not None


def read_usage(pid: int) -> Optional[RawUsage]:
    if _LIBPROC is None or _TIMEBASE is None:
        return None
    info = ProcTaskInfo()
    size = ctypes.sizeof(info)
    ctypes.set_errno(0)
    got = _LIBPROC.proc_pidinfo(int(pid), PROC_PIDTASKINFO, 0, ctypes.byref(info), size)
    if got != size:
        if got <= 0 and ctypes.get_errno() == errno.ESRCH:
            raise ProcessGone(pid)
        return None
    numer, denom = _TIMEBASE
    return RawUsage(int(info.pti_resident_size), mach_to_seconds(info.pti_total_user + info.pti_total_system, numer, denom))
