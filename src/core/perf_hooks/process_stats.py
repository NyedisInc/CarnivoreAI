
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


class ProcessStatsError(Exception):
    """`ps` could not be run or its output could not be read."""


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
        tracked: List[Tuple[int, float]] = [(r.pid, r.cpu_seconds) for r in servers.values()]
        if own:
            tracked.append((own.pid, own.cpu_seconds))
        self._last_cpu = dict(tracked)
        self._last_wall = now
        return report
