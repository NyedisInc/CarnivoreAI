
from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Tuple

import structlog

from src.core.agent_families import DEFAULT_FAMILY
from src.core.session_token_usage import claude_reader
from src.core.session_transcript_presence import CONVERSATION_ABSENT, CONVERSATION_PRESENT
from src.core.timers.index import TimerIndex, read_timer_index
from src.core.timers.reader import PROCESS_UNKNOWN, derive_timers
from src.core.timers.session import process_fact_for

logger = structlog.get_logger(__name__)

REFRESH_SECONDS: float = 30.0

MAX_ENTRIES: int = 256

STATE_OK = "ok"
STATE_ABSENT = "absent"
STATE_UNCHECKED = "unchecked"
STATE_NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class TimerTally:

    state: str
    live: Optional[int] = None
    next_fire_at: Optional[datetime] = None


NOT_APPLICABLE = TimerTally(STATE_NOT_APPLICABLE)
UNCHECKED = TimerTally(STATE_UNCHECKED)
ABSENT = TimerTally(STATE_ABSENT, live=0)


@dataclass
class _Entry:

    path: Optional[Path]
    located_at: float
    missing: TimerTally = UNCHECKED
    key: Optional[Tuple[int, int]] = None
    index: Optional[TimerIndex] = None


def _mtime_key(path: Path) -> Optional[Tuple[int, int]]:
    try:
        stat = os.stat(path)
    except FileNotFoundError:
        return None
    return (stat.st_size, stat.st_mtime_ns)


class TimerTallyCache:

    def __init__(self, *, projects_dir: Optional[Path] = None, clock=None) -> None:
        self._projects_dir = projects_dir
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._entries: "OrderedDict[str, _Entry]" = OrderedDict()

    def tally(
        self,
        family: Optional[str],
        conversation_uuid: Optional[str],
        working_dir: Optional[str],
        registry: Any,
        now: Optional[datetime] = None,
    ) -> TimerTally:
        if family is not None and family != DEFAULT_FAMILY:
            return NOT_APPLICABLE
        if not conversation_uuid:
            return ABSENT
        try:
            index = self._index(conversation_uuid, working_dir)
        except OSError as exc:
            logger.debug("timer_tally_unreadable", error=str(exc),
                         error_type=type(exc).__name__)
            return UNCHECKED
        if isinstance(index, TimerTally):
            return index
        process = process_fact_for(registry, conversation_uuid)
        _rows, counts, upcoming = derive_timers(
            index, process, now or datetime.now(timezone.utc))
        if process.state == PROCESS_UNKNOWN and counts.unknown > 0:
            return UNCHECKED
        return TimerTally(STATE_OK, live=counts.live, next_fire_at=upcoming)

    def _index(self, uuid: str, working_dir: Optional[str]):
        at = self._clock()
        with self._lock:
            entry = self._entries.get(uuid)
            if entry is not None:
                self._entries.move_to_end(uuid)
        stale_miss = (entry is not None and entry.path is None
                      and at - entry.located_at >= REFRESH_SECONDS)
        gone = entry is not None and entry.path is not None and not entry.path.is_file()
        if entry is None or stale_miss or gone:
            location = claude_reader.locate_transcript(
                uuid, working_dir=working_dir, projects_dir=self._projects_dir)
            path = location.path if location.outcome == CONVERSATION_PRESENT else None
            entry = _Entry(path=path, located_at=at)
            if path is None:
                entry.missing = ABSENT if location.outcome == CONVERSATION_ABSENT else UNCHECKED
            with self._lock:
                self._entries[uuid] = entry
                self._entries.move_to_end(uuid)
                while len(self._entries) > MAX_ENTRIES:
                    self._entries.popitem(last=False)
        if entry.path is None:
            return entry.missing
        key = _mtime_key(entry.path)
        if entry.index is None or entry.key != key:
            index = read_timer_index(entry.path)
            if index is None:
                return UNCHECKED
            entry.key, entry.index = key, index
        return entry.index


__all__ = ["TimerTally", "TimerTallyCache", "NOT_APPLICABLE", "UNCHECKED", "ABSENT",
           "REFRESH_SECONDS", "MAX_ENTRIES"]
