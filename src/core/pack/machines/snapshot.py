
from __future__ import annotations

import os
import platform
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.core import host_metrics
from src.core.dev_tools import git_guard

SNAPSHOT_VERSION = 1
TOOLS = (("python3.12", "python3.12"), ("python3", "python3"), ("node", "node"), ("npm", "npm"), ("git", "git"),
         ("gh", "gh"), ("docker", "docker"), ("tmux", "tmux"), ("claude", "claude"), ("playwright", "playwright"))
_GB = 1024.0 ** 3
BATTERY_TTL = 60.0
HID_TTL = 30.0


def _run(argv: List[str], timeout: float = 3.0) -> Optional[str]:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _sysctl(name: str) -> Optional[str]:
    out = _run(["sysctl", "-n", name])
    return out.strip() if out else None


def read_specs() -> Dict[str, Any]:
    memsize = _sysctl("hw.memsize")
    return {"model": _sysctl("hw.model"), "chip": _sysctl("machdep.cpu.brand_string"), "cores": os.cpu_count(),
            "mem_total_gb": round(int(memsize) / _GB, 1) if memsize and memsize.isdigit() else None,
            "os": f"{platform.system()} {platform.release()}", "arch": platform.machine()}


def read_toolchain() -> Dict[str, Any]:
    found = {name: git_guard.tool_available(binary) for name, binary in TOOLS}
    cache = Path.home() / "Library" / "Caches" / "ms-playwright"
    found["playwright_browsers"] = cache.is_dir() and any(cache.iterdir())
    return found


def parse_battery(text: Optional[str]) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    on_battery = "'Battery Power'" in text
    if "InternalBattery" not in text:
        return {"present": False, "percent": None, "charging": None, "on_battery": False}
    match = re.search(r"(\d+)%;\s*([a-z ]+?);", text)
    state = match.group(2).strip() if match else ""
    return {"present": True, "percent": int(match.group(1)) if match else None,
            "charging": None if not match else state in ("charging", "finishing charge"), "on_battery": on_battery}


def parse_hid_idle(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    match = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', text)
    return int(match.group(1)) / 1e9 if match else None


class SnapshotCollector:

    def __init__(self, state_dir: Callable[[], str], *, clock: Callable[[], float] = time.monotonic,
                 run: Callable[[List[str]], Optional[str]] = _run) -> None:
        self._state_dir, self._clock, self._run = state_dir, clock, run
        self._lock = threading.Lock()
        self._specs: Optional[Dict[str, Any]] = None
        self._toolchain: Optional[Dict[str, Any]] = None
        self._battery: Optional[Dict[str, Any]] = None
        self._battery_at = float("-inf")
        self._hid: Optional[float] = None
        self._hid_at = float("-inf")

    def rescan(self) -> Dict[str, Any]:
        with self._lock:
            self._toolchain = read_toolchain()
            return dict(self._toolchain)

    def hid_idle_seconds(self, wanted: bool) -> Optional[float]:
        if not wanted:
            return None
        with self._lock:
            if self._clock() - self._hid_at >= HID_TTL:
                self._hid = parse_hid_idle(self._run(["ioreg", "-c", "IOHIDSystem", "-d", "4", "-r", "-k", "HIDIdleTime"]))
                self._hid_at = self._clock()
            return self._hid

    def _battery_now(self) -> Optional[Dict[str, Any]]:
        if self._clock() - self._battery_at >= BATTERY_TTL:
            self._battery = parse_battery(self._run(["pmset", "-g", "batt"])) if platform.system() == "Darwin" else None
            self._battery_at = self._clock()
        return self._battery

    def collect(self, *, install_id: str, label: str, app_version: str, reserve: Dict[str, Any],
                restrictions: Dict[str, Any], capabilities: List[str], hid_idle: Optional[float],
                now: Optional[float] = None) -> Dict[str, Any]:
        with self._lock:
            if self._specs is None:
                self._specs = read_specs()
            if self._toolchain is None:
                self._toolchain = read_toolchain()
            specs, toolchain, battery = dict(self._specs), dict(self._toolchain), self._battery_now()
        memory, disk, load = host_metrics.collect_memory(), host_metrics.collect_disk(self._state_dir()), host_metrics.collect_load()
        total = memory.get("total_bytes") if memory["available"] else None
        avail = memory.get("available_bytes") if memory["available"] else None
        return {
            "v": SNAPSHOT_VERSION, "install_id": install_id, "label": label, "app_version": app_version,
            "taken_at": time.time() if now is None else now, "specs": specs,
            "load": {
                "cores": load.get("cpu_count") if load["available"] else specs["cores"],
                "load_1": load.get("load_1") if load["available"] else None,
                "load_5": load.get("load_5") if load["available"] else None,
                "busy_cores": load.get("busy_cores_1") if load["available"] else None,
                "busy_cores_5": load.get("busy_cores_5") if load["available"] else None,
                "cpu_source": load.get("cpu_source") if load["available"] else None,
                "cpu_percent": None,
                "memory_percent": memory.get("used_percent") if memory["available"] else None,
                "mem_total_gb": round(total / _GB, 1) if total else None,
                "mem_available_gb": round(avail / _GB, 1) if avail is not None else None,
                "disk_percent": disk.get("used_percent") if disk["available"] else None,
                "disk_free_gb": round(disk["free_bytes"] / _GB, 1) if disk["available"] else None,
                "uptime_seconds": host_metrics.collect_host()["uptime_seconds"],
            },
            "battery": battery, "hid_idle_seconds": hid_idle, "toolchain": toolchain, "reserve": reserve,
            "restrictions": restrictions, "capabilities": capabilities, "throttled": 0, "agents": None,
        }
