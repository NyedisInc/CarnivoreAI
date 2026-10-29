
from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger()

PS_TIMEOUT_SECONDS = 5.0

_SOCKET_FLAG = re.compile(r"\s-L\s+(\S+)")
_TYPE_FLAG = re.compile(r"\s--type=(\S+)")

_SHELL_MARKERS = ("/Carnivore.app/Contents/", "Carnivore Helper",
                  "/node_modules/electron/dist/Electron.app/")


class ProcessStatsError(Exception):
    pass


@dataclass(frozen=True)
class ProcRow:

    pid: int
    ppid: int
    cpu_seconds: float
    rss_kib: int
    command: str


def parse_cputime(text: str) -> float:
    days = 0
    if "-" in text:
        day_text, text = text.split("-", 1)
        days = int(day_text)
    total = 0.0
    for part in text.split(":"):
        total = total * 60 + float(part)
    return days * 86400 + total


def parse_ps(output: str) -> List[ProcRow]:
    rows: List[ProcRow] = []
    for line in output.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        try:
            rows.append(ProcRow(int(parts[0]), int(parts[1]), parse_cputime(parts[2]),
                                int(parts[3]), parts[4]))
        except ValueError:
            continue
    return rows


def read_processes() -> List[ProcRow]:
    try:
        done = subprocess.run(["ps", "-axo", "pid=,ppid=,time=,rss=,command="],
                              capture_output=True, text=True, timeout=PS_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProcessStatsError(str(exc)) from exc
    if done.returncode != 0:
        raise ProcessStatsError(f"ps exited {done.returncode}")
    return parse_ps(done.stdout)


def tmux_servers(rows: List[ProcRow]) -> Dict[str, ProcRow]:
    found: Dict[str, ProcRow] = {}
    for row in rows:
        exe = row.command.split(None, 1)[0] if row.command else ""
        if row.ppid != 1 or os.path.basename(exe) != "tmux":
            continue
        match = _SOCKET_FLAG.search(row.command)
        found[match.group(1) if match else "default"] = row
    return found


def shell_role(row: ProcRow) -> Optional[str]:
    argv0 = row.command.split(" --", 1)[0]
    if not any(marker in argv0 for marker in _SHELL_MARKERS):
        return None
    match = _TYPE_FLAG.search(row.command)
    if match is None:
        return "main" if "/Contents/MacOS/" in argv0 else None
    kind = match.group(1)
    return {"renderer": "renderer", "gpu-process": "gpu", "utility": "utility"}.get(kind)


def window_server(rows: List[ProcRow]) -> Optional[ProcRow]:
    return next((r for r in rows if os.path.basename(r.command.split(None, 1)[0] if r.command else "") == "WindowServer"), None)


@dataclass
class ProcessSampler:

    own_pid: int = field(default_factory=os.getpid)
    _last_wall: Optional[float] = None
    _last_cpu: Dict[int, float] = field(default_factory=dict)

    def _cpu_pct(self, row: ProcRow, elapsed: Optional[float]) -> Optional[float]:
        before = self._last_cpu.get(row.pid)
        if elapsed is None or elapsed <= 0 or before is None:
            return None
        return round(max(0.0, row.cpu_seconds - before) / elapsed * 100.0, 2)

    def sample(self, rows: Optional[List[ProcRow]] = None) -> Dict[str, object]:
        rows = read_processes() if rows is None else rows
        now = time.monotonic()
        elapsed = None if self._last_wall is None else now - self._last_wall

        def describe(row: ProcRow) -> Dict[str, object]:
            return {"pid": row.pid, "cpu_pct": self._cpu_pct(row, elapsed),
                    "rss_mb": round(row.rss_kib / 1024.0, 1)}

        own = next((r for r in rows if r.pid == self.own_pid), None)
        servers = tmux_servers(rows)
        report: Dict[str, object] = {
            "server": describe(own) if own else None,
            "tmux": {name: describe(row) for name, row in sorted(servers.items())},
        }
        shell: Dict[str, object] = {"main": None, "renderer": [], "gpu": None, "utility": []}
        shell_rows: List[ProcRow] = []
        for row in rows:
            role = shell_role(row)
            if role is None:
                continue
            shell_rows.append(row)
            if role in ("renderer", "utility"):
                shell[role].append(describe(row))  # type: ignore[union-attr]
            elif shell[role] is None:
                shell[role] = describe(row)
        report["shell"] = shell
        wserver = window_server(rows)
        report["window_server"] = describe(wserver) if wserver else None
        tracked: List[Tuple[int, float]] = [(r.pid, r.cpu_seconds) for r in servers.values()]
        tracked += [(r.pid, r.cpu_seconds) for r in shell_rows]
        if wserver:
            tracked.append((wserver.pid, wserver.cpu_seconds))
        if own:
            tracked.append((own.pid, own.cpu_seconds))
        self._last_cpu = dict(tracked)
        self._last_wall = now
        return report
