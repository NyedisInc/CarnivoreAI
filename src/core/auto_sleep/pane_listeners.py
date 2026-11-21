
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, FrozenSet, List, Optional

from src.core.auto_sleep.pane_ports import pid_holds_listener
from src.core.conversation_writers import MeasureError, ProcessTable, read_process_table

__all__ = [
    "ListenerSnapshot",
    "MeasureError",
    "PassSnapshot",
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


@dataclass(frozen=True)
class ListenerSnapshot:

    listeners: Optional[FrozenSet[int]]
    table: ProcessTable

    def pane_listeners(self, pane_pid: int) -> List[int]:
        if pane_pid not in self.table.rows:
            raise MeasureError("the pane pid is not in the process table")
        if self.listeners is None:
            return [proc.pid for proc in self.table.descendants(pane_pid) if pid_holds_listener(proc.pid)]
        return [proc.pid for proc in self.table.descendants(pane_pid) if proc.pid in self.listeners]


def take_snapshot() -> ListenerSnapshot:
    return ListenerSnapshot(listeners=None, table=read_process_table())


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
