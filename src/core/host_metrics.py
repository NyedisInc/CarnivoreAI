
from __future__ import annotations

import ctypes
import ctypes.util
import os
import platform
import shutil
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger()

PROBE_TIMEOUT_SECONDS: float = 3.0


def unavailable(reason: str) -> Dict[str, Any]:
    return {"available": False, "error": reason}


def _run(argv: List[str]) -> Optional[str]:
    found = shutil.which(argv[0]) if argv else None
    if not found:
        return None
    try:
        proc = subprocess.run(
            [found, *argv[1:]],
            capture_output=True,
            check=False,
            timeout=PROBE_TIMEOUT_SECONDS,
            close_fds=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("host_metric_probe_failed", argv=argv[0], error=str(exc))
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", errors="replace")


def _sysctl_int(name: str) -> Optional[int]:
    out = _run(["sysctl", "-n", name])
    if out is None:
        return None
    try:
        return int(out.strip())
    except ValueError:
        return None


_BOOT_STATIC: Dict[str, int] = {}


def _static_sysctl_int(name: str) -> Optional[int]:
    if name not in _BOOT_STATIC:
        value = _sysctl_int(name)
        if value is None:
            return None
        _BOOT_STATIC[name] = value
    return _BOOT_STATIC[name]


def collect_memory() -> Dict[str, Any]:
    system = platform.system()
    if system == "Darwin":
        return _memory_darwin()
    if system == "Linux":
        return _memory_linux()
    return unavailable(f"no memory probe for {system.lower() or 'this os'}")


VM_STAT_SHARE_SECONDS = 2.0
_clock: Callable[[], float] = time.monotonic
_VM_STAT_LOCK = threading.Lock()
_VM_STAT: Optional[Tuple[float, str]] = None


def clear_vm_stat_cache() -> None:
    global _VM_STAT
    with _VM_STAT_LOCK:
        _VM_STAT = None


def _vm_stat_shared() -> Optional[str]:
    global _VM_STAT
    with _VM_STAT_LOCK:
        now = _clock()
        if _VM_STAT is not None and 0 <= now - _VM_STAT[0] < VM_STAT_SHARE_SECONDS:
            return _VM_STAT[1]
        out = _run(["vm_stat"])
        _VM_STAT = None if out is None else (now, out)
        return out


_DEFAULT_RUN = _run


class _VMStats64(ctypes.Structure):

    _fields_ = [
        ("free_count", ctypes.c_uint32),
        ("active_count", ctypes.c_uint32),
        ("inactive_count", ctypes.c_uint32),
        ("wire_count", ctypes.c_uint32),
        ("zero_fill_count", ctypes.c_uint64),
        ("reactivations", ctypes.c_uint64),
        ("pageins", ctypes.c_uint64),
        ("pageouts", ctypes.c_uint64),
        ("faults", ctypes.c_uint64),
        ("cow_faults", ctypes.c_uint64),
        ("lookups", ctypes.c_uint64),
        ("hits", ctypes.c_uint64),
        ("purges", ctypes.c_uint64),
        ("purgeable_count", ctypes.c_uint32),
        ("speculative_count", ctypes.c_uint32),
        ("decompressions", ctypes.c_uint64),
        ("compressions", ctypes.c_uint64),
        ("swapins", ctypes.c_uint64),
        ("swapouts", ctypes.c_uint64),
        ("compressor_page_count", ctypes.c_uint32),
        ("throttled_count", ctypes.c_uint32),
        ("external_page_count", ctypes.c_uint32),
        ("internal_page_count", ctypes.c_uint32),
        ("total_uncompressed_pages_in_compressor", ctypes.c_uint64),
    ]


_HOST_VM_INFO64 = 4
_MACH_VM: Optional[Tuple[ctypes.CDLL, int]] = None
_MACH_VM_FAILED = False
_PAGEOUTS_LOCK = threading.Lock()
_LAST_PAGEOUTS: Optional[Tuple[float, int]] = None


def _pageouts_rate(total_pageouts: int) -> Optional[float]:
    global _LAST_PAGEOUTS
    now = _clock()
    with _PAGEOUTS_LOCK:
        prev = _LAST_PAGEOUTS
        _LAST_PAGEOUTS = (now, total_pageouts)
    if prev is None or now - prev[0] <= 0 or total_pageouts < prev[1]:
        return None
    return round((total_pageouts - prev[1]) / (now - prev[0]), 2)


def _mach_vm_memory() -> Optional[Dict[str, Any]]:
    global _MACH_VM, _MACH_VM_FAILED
    if _MACH_VM_FAILED:
        return None
    if _MACH_VM is None:
        try:
            path = ctypes.util.find_library("System")
            if not path:
                _MACH_VM_FAILED = True
                return None
            lib = ctypes.CDLL(path)
            lib.mach_host_self.restype = ctypes.c_uint32
            lib.mach_host_self.argtypes = []
            lib.host_statistics64.restype = ctypes.c_int
            lib.host_statistics64.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            _MACH_VM = (lib, int(lib.mach_host_self()))
        except (OSError, AttributeError, TypeError):
            _MACH_VM_FAILED = True
            return None
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        total = int(os.sysconf("SC_PHYS_PAGES")) * page_size
    except (ValueError, OSError, AttributeError):
        return None
    if total <= 0 or page_size <= 0:
        return None
    lib, port = _MACH_VM
    st = _VMStats64()
    count = ctypes.c_uint32(ctypes.sizeof(st) // 4)
    if lib.host_statistics64(port, _HOST_VM_INFO64, ctypes.byref(st), ctypes.byref(count)) != 0:
        return None
    reclaimable = int(st.free_count) + int(st.inactive_count) + int(st.purgeable_count)
    avail = min(reclaimable * page_size, total)
    used = total - avail
    return {
        "available": True,
        "error": None,
        "total_bytes": total,
        "used_bytes": used,
        "available_bytes": avail,
        "used_percent": round(used * 100.0 / total, 1),
        "compressed_bytes": int(st.compressor_page_count) * page_size,
        "wired_bytes": int(st.wire_count) * page_size,
        "pageouts_per_s": _pageouts_rate(int(st.pageouts)),
    }


def _memory_darwin() -> Dict[str, Any]:
    if _run is _DEFAULT_RUN:
        fast = _mach_vm_memory()
        if fast is not None:
            return fast
    total = _static_sysctl_int("hw.memsize")
    if not total:
        return unavailable("sysctl hw.memsize unreadable")

    out = _vm_stat_shared()
    if out is None:
        return unavailable("vm_stat unavailable")

    page_size = 4096
    counts: Dict[str, int] = {}
    for line in out.splitlines():
        if "page size of" in line:
            for token in line.replace(".", " ").split():
                if token.isdigit():
                    page_size = int(token)
                    break
            continue
        if ":" not in line:
            continue
        key, _, raw = line.partition(":")
        digits = raw.strip().rstrip(".")
        if digits.isdigit():
            counts[key.strip().lower()] = int(digits)

    if not counts:
        return unavailable("vm_stat output unparseable")

    reclaimable = sum(
        counts.get(key, 0)
        for key in ("pages free", "pages inactive", "pages speculative",
                    "pages purgeable")
    )
    avail = min(reclaimable * page_size, total)
    used = total - avail
    return {
        "available": True,
        "error": None,
        "total_bytes": total,
        "used_bytes": used,
        "available_bytes": avail,
        "used_percent": round(used * 100.0 / total, 1),
    }


def _memory_linux() -> Dict[str, Any]:
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            raw = handle.read()
    except OSError as exc:
        return unavailable(f"/proc/meminfo unreadable: {exc.strerror}")

    fields: Dict[str, int] = {}
    for line in raw.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            fields[key.strip()] = int(parts[0]) * 1024

    total = fields.get("MemTotal")
    avail = fields.get("MemAvailable")
    if not total or avail is None:
        return unavailable("/proc/meminfo missing MemTotal/MemAvailable")

    used = total - avail
    return {
        "available": True,
        "error": None,
        "total_bytes": total,
        "used_bytes": used,
        "available_bytes": avail,
        "used_percent": round(used * 100.0 / total, 1),
    }


def collect_disk(path: str = "/") -> Dict[str, Any]:
    try:
        usage = shutil.disk_usage(path)
    except OSError as exc:
        return unavailable(f"disk usage for {path} unreadable: {exc.strerror}")
    if usage.total <= 0:
        return unavailable(f"disk usage for {path} reported zero total")
    return {
        "available": True,
        "error": None,
        "path": path,
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "used_percent": round(usage.used * 100.0 / usage.total, 1),
    }


def collect_load() -> Dict[str, Any]:
    try:
        one, five, fifteen = os.getloadavg()
    except (OSError, AttributeError) as exc:
        return unavailable(f"load average unavailable: {exc}")
    from src.core.machine_stats import cpu_busy

    cores = os.cpu_count() or 0
    busy = cpu_busy.METER.busy_cores(cores)
    return {
        "available": True,
        "error": None,
        "load_1": round(one, 2),
        "load_5": round(five, 2),
        "load_15": round(fifteen, 2),
        "cpu_count": cores,
        "busy_cores_15s": busy.get("busy_15s"),
        "busy_cores_1": busy["busy_1"],
        "busy_cores_5": busy["busy_5"],
        "cpu_source": busy["source"],
    }


def collect_host() -> Dict[str, Any]:
    return {
        "available": True,
        "error": None,
        "hostname": platform.node() or "unknown",
        "os": f"{platform.system()} {platform.release()}".strip(),
        "uptime_seconds": _host_uptime_seconds(),
    }


def _host_uptime_seconds() -> Optional[int]:
    system = platform.system()
    if system == "Linux":
        try:
            with open("/proc/uptime", "r", encoding="utf-8") as handle:
                return int(float(handle.read().split()[0]))
        except (OSError, ValueError, IndexError):
            return None
    if system == "Darwin":
        if "kern.boottime" not in _BOOT_STATIC:
            out = _run(["sysctl", "-n", "kern.boottime"])
            if not out:
                return None
            marker = "sec ="
            if marker not in out:
                return None
            tail = out.split(marker, 1)[1].lstrip()
            digits = ""
            for char in tail:
                if not char.isdigit():
                    break
                digits += char
            if not digits:
                return None
            _BOOT_STATIC["kern.boottime"] = int(digits)
        digits = str(_BOOT_STATIC["kern.boottime"])
        return max(0, int(time.time()) - int(digits))
    return None


def collect() -> Dict[str, Any]:
    return {
        "host": collect_host(),
        "memory": collect_memory(),
        "disk": collect_disk(),
        "load": collect_load(),
    }
