"""How many background shells and monitors a claude session has open
(issue #1044 follow-up).

THE CONTINUOUS SOURCE. A background shell is a live process, so the count
is MEASURED from the process tree on every cycle: a direct child of the
claude pid whose stdout is ``tasks/<id>.output`` names its task id. A
foreground Bash call holds its task file on stdout too (measured the same
day), so a child counts only when that id was recorded as a background
launch (``backgroundTaskId``) in some file of this conversation
(:func:`src.core.subagents.parked_launches.conversation_launches`). A
shell's end needs no notice: its process is gone. A Monitor keeps its
stdio on pipes (``subagents.parked_work``), so a Monitor counts from its
records alone: launched by the current claude process, never stopped or
notified with a status, and inside its ``timeoutMs`` when it has one.

CACHED WHERE SOUND. The transcript half is re-read when the parent
changes, the ``subagents/`` folder changes, a live task id has not been
looked up yet, a Monitor deadline passes, or
:data:`REFRESH_SECONDS` elapse; the process half is never cached.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple

import structlog

from src.core.attention.output_holders import open_file_path
from src.core.attention.turn_counts import KIND_MONITOR, KIND_SHELL
from src.core.background_work.listing import task_id_of
from src.core.subagents.parked_launches import OpenLaunch, conversation_launches
from src.core.subagents.reader import subagents_dir_for

logger = structlog.get_logger(__name__)

REFRESH_SECONDS: float = 10.0

MAX_ENTRIES: int = 256


@dataclass(frozen=True)
class RecordedLaunches:

    shell_ids: FrozenSet[str] = frozenset()
    monitors: Tuple[OpenLaunch, ...] = ()


def recorded_launches(
    launches: Iterable[Tuple[OpenLaunch, bool]],
    *,
    process_started_at: Optional[datetime],
) -> RecordedLaunches:
    shells = set()
    monitors: List[OpenLaunch] = []
    for launch, retired in launches:
        if launch.kind == KIND_SHELL:
            shells.add(launch.task_id)
        elif launch.kind == KIND_MONITOR and not retired:
            if process_started_at is None or launch.launched_at >= process_started_at:
                monitors.append(launch)
    return RecordedLaunches(frozenset(shells), tuple(monitors))


def live_task_ids(
    claude_pid: int,
    process_parents: Mapping[int, int],
    *,
    stdout_of: Callable[[int], Optional[str]] = lambda pid: open_file_path(pid, 1),
) -> FrozenSet[str]:
    found = set()
    for pid, ppid in process_parents.items():
        if ppid == claude_pid and pid != claude_pid:
            task_id = task_id_of(stdout_of(pid))
            if task_id is not None:
                found.add(task_id)
    return frozenset(found)


def count_open(live: FrozenSet[str], recorded: RecordedLaunches, now: datetime) -> int:
    shells = len(live & recorded.shell_ids)
    monitors = sum(1 for m in recorded.monitors if m.deadline is None or m.deadline > now)
    return shells + monitors


def _stat_key(path: Path) -> Optional[Tuple[int, int]]:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_size, stat.st_mtime_ns)


@dataclass
class _Entry:

    key: Tuple
    recorded: RecordedLaunches
    until: float
    seen: FrozenSet[str] = frozenset()


class BackgroundCountReader:

    def __init__(self, *, clock: Optional[Callable[[], float]] = None,
                 stdout_of: Optional[Callable[[int], Optional[str]]] = None) -> None:
        self._clock = clock or time.monotonic
        self._stdout_of = stdout_of or (lambda pid: open_file_path(pid, 1))
        self._lock = threading.Lock()
        self._entries: Dict[str, _Entry] = {}

    def read(
        self,
        parent_path: Optional[Path],
        *,
        claude_pid: Optional[int],
        process_parents: Optional[Mapping[int, int]],
        process_started_at: Optional[datetime],
        now: datetime,
    ) -> Optional[int]:
        """This cycle's count, or None when it could not be measured.

        Inputs: parent_path (Path | None) - the located conversation.
          claude_pid (int | None) - from a positive registry read naming
          this conversation. process_parents (mapping | None) - the shared
          snapshot. process_started_at (datetime | None). now (datetime).
        Output: int | None - None without a transcript, a pid or a snapshot.
        """
        if parent_path is None or claude_pid is None or not process_parents:
            return None
        live = live_task_ids(claude_pid, process_parents, stdout_of=self._stdout_of)
        recorded = self._recorded(parent_path, live, process_started_at, now)
        if recorded is None:
            return None
        return count_open(live, recorded, now)

    def _recorded(self, parent_path: Path, live: FrozenSet[str],
                  process_started_at: Optional[datetime],
                  now: datetime) -> Optional[RecordedLaunches]:
        key = (_stat_key(parent_path), _stat_key(subagents_dir_for(parent_path)),
               process_started_at)
        at = self._clock()
        with self._lock:
            entry = self._entries.get(str(parent_path))
        if (entry is not None and entry.key == key and at < entry.until
                and live <= (entry.recorded.shell_ids | entry.seen)
                and all(m.deadline is None or m.deadline > now
                        for m in entry.recorded.monitors)):
            return entry.recorded
        launches = conversation_launches(parent_path)
        if launches is None:
            logger.debug("background_count_unreadable", path=str(parent_path))
            return None
        recorded = recorded_launches(launches, process_started_at=process_started_at)
        with self._lock:
            self._entries.pop(str(parent_path), None)
            self._entries[str(parent_path)] = _Entry(key, recorded, at + REFRESH_SECONDS, live)
            while len(self._entries) > MAX_ENTRIES:
                self._entries.pop(next(iter(self._entries)))
        return recorded


__all__ = [
    "BackgroundCountReader", "RecordedLaunches", "count_open", "live_task_ids",
    "recorded_launches",
]
