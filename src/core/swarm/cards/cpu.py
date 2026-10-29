
from __future__ import annotations

import ctypes
import ctypes.util
import sys
from typing import Optional, Tuple

import structlog

logger = structlog.get_logger()

HOST_CPU_LOAD_INFO = 3
KERN_SUCCESS = 0
Ticks = Tuple[int, int, int, int]

_PROC_STAT = "/proc/stat"
_mach: Optional[Tuple[ctypes.CDLL, int]] = None
_mach_failed = False


def _mach_host() -> Optional[Tuple[ctypes.CDLL, int]]:
    global _mach, _mach_failed
    if _mach is None and not _mach_failed:
        try:
            lib = ctypes.CDLL(ctypes.util.find_library("System"))
            lib.mach_host_self.restype = ctypes.c_uint32
            lib.mach_host_self.argtypes = []
            lib.host_statistics.restype = ctypes.c_int
            lib.host_statistics.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            _mach = (lib, int(lib.mach_host_self()))
        except (OSError, AttributeError, TypeError) as exc:
            _mach_failed = True
            logger.warning("card_cpu_mach_unavailable", error_type=type(exc).__name__)
    return _mach


def _mac_ticks() -> Optional[Ticks]:
    host = _mach_host()
    if host is None:
        return None
    lib, port = host
    buf = (ctypes.c_uint32 * 4)()
    count = ctypes.c_uint32(4)
    if lib.host_statistics(port, HOST_CPU_LOAD_INFO, ctypes.byref(buf), ctypes.byref(count)) != KERN_SUCCESS or count.value != 4:
        return None
    return int(buf[0]), int(buf[1]), int(buf[2]), int(buf[3])


def _linux_ticks() -> Optional[Ticks]:
    try:
        with open(_PROC_STAT, "r", encoding="ascii") as handle:
            fields = handle.readline().split()
    except (OSError, UnicodeDecodeError):
        return None
    if len(fields) < 5 or fields[0] != "cpu":
        return None
    try:
        user, nice, system, idle = (int(fields[i]) for i in range(1, 5))
        iowait = int(fields[5]) if len(fields) > 5 else 0
    except ValueError:
        return None
    return user, system, idle + iowait, nice


def ticks() -> Optional[Ticks]:
    if sys.platform == "darwin":
        return _mac_ticks()
    if sys.platform.startswith("linux"):
        return _linux_ticks()
    return None


def busy_pct(prev: Optional[Ticks], cur: Optional[Ticks]) -> Optional[float]:
    if prev is None or cur is None:
        return None
    deltas = [c - p for p, c in zip(prev, cur)]
    total = sum(deltas)
    if total <= 0 or min(deltas) < 0:
        return None
    return max(0.0, min(100.0, 100.0 * (1.0 - deltas[2] / total)))
