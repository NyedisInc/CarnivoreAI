
from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from typing import Callable, FrozenSet, List, Optional

from src.core.conversation_writers import MeasureError, ProcessTable, read_process_table

__all__ = [
    "ListenerSnapshot",
    "MeasureError",
    "PassSnapshot",
    "listening_pids",
    "parse_lsof_pids",
    "take_snapshot",
]

LSOF_PATH: str = "/usr/sbin/lsof"

LSOF_TIMEOUT_SECONDS: float = 5.0


def parse_lsof_pids(stdout: str) -> FrozenSet[int]:
    pids = set()
    for line in stdout.splitlines():
        if not line.startswith("p"):
            continue
        try:
            pids.add(int(line[1:]))
        except ValueError as exc:
            raise MeasureError("lsof printed a process line that is not a pid") from exc
    return frozenset(pids)


def listening_pids() -> FrozenSet[int]:
    try:
        proc = subprocess.run(
            [LSOF_PATH, "-nP", "-iTCP", "-sTCP:LISTEN", "-Fp"],
            capture_output=True, text=True, timeout=LSOF_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MeasureError(f"lsof could not run: {type(exc).__name__}") from exc
    if proc.returncode == 1 and not proc.stdout.strip() and not proc.stderr.strip():
        return frozenset()
    if proc.returncode != 0:
        raise MeasureError(f"lsof exited {proc.returncode}")
    pids = parse_lsof_pids(proc.stdout)
    if not pids:
        raise MeasureError("lsof exited 0 and named no process")
    return pids


@dataclass(frozen=True)
class ListenerSnapshot:

    listeners: FrozenSet[int]
    table: ProcessTable

    def pane_listeners(self, pane_pid: int) -> List[int]:
        if pane_pid not in self.table.rows:
            raise MeasureError("the pane pid is not in the process table")
        return [proc.pid for proc in self.table.descendants(pane_pid) if proc.pid in self.listeners]


def take_snapshot() -> ListenerSnapshot:
    listeners = listening_pids()
    return ListenerSnapshot(listeners=listeners, table=read_process_table())


class PassSnapshot:

    def __init__(self, take: Callable[[], ListenerSnapshot]) -> None:
        self._take = take
        self._snapshot: Optional[ListenerSnapshot] = None
        self._error: Optional[str] = None

    async def get(self) -> ListenerSnapshot:
        if self._snapshot is None and self._error is None:
            try:
                self._snapshot = await asyncio.to_thread(self._take)
            except MeasureError as exc:
                self._error = str(exc)
        if self._snapshot is None:
            raise MeasureError(self._error or "no snapshot")
        return self._snapshot
