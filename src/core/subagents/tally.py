
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Tuple

import structlog

from src.core.agent_families import DEFAULT_FAMILY
from src.core.attention.registry_record import REG_OK
from src.core.session_token_usage import claude_reader
from src.core.session_transcript_presence import CONVERSATION_ABSENT, CONVERSATION_PRESENT
from src.core.subagents.parent_index import parse_timestamp
from src.core.subagents.parent_index import read_completion_index
from src.core.subagents.reader import subagents_dir_for
from src.core.subagents.stall import StalledAgent, STALL_NOTIFY_AFTER, read_marked, stalled_agents
from src.core.subagents.scan_inputs import (agent_files_signature_read, index_snapshot,
                                            read_agent_files_signature)

logger = structlog.get_logger(__name__)

REFRESH_SECONDS: float = 30.0

MAX_ENTRIES: int = 256

STATE_OK = "ok"
STATE_ABSENT = "absent"
STATE_UNCHECKED = "unchecked"
STATE_NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class SubagentTally:

    state: str
    running: Optional[int] = None
    total: Optional[int] = None
    unknown: Optional[int] = None
    last_activity_at: Optional[datetime] = None
    stalled: Optional[int] = None
    long_stalled: Tuple[StalledAgent, ...] = ()


NOT_APPLICABLE = SubagentTally(STATE_NOT_APPLICABLE)
UNCHECKED = SubagentTally(STATE_UNCHECKED)
ABSENT = SubagentTally(STATE_ABSENT, running=0, total=0, unknown=0, stalled=0)


@dataclass
class _Entry:

    path: Optional[Path]
    located_at: float
    key: Optional[tuple] = None
    tally: Optional[SubagentTally] = None
    computed_at: float = 0.0
    inputs: Optional[tuple] = None


def process_start_for(record: Any, conversation_uuid: Optional[str]) -> Optional[datetime]:
    if record is None or not conversation_uuid:
        return None
    if getattr(record, "verdict", None) != REG_OK:
        return None
    if conversation_uuid not in (getattr(record, "session_uuid", None),
                                 getattr(record, "record_session_uuid", None)):
        return None
    return getattr(record, "started_at", None)


def _mtime_key(path: Path) -> Optional[Tuple[int, int]]:
    try:
        stat = os.stat(path)
    except FileNotFoundError:
        return None
    return (stat.st_size, stat.st_mtime_ns)


class SubagentTallyCache:

    def __init__(self, *, projects_dir: Optional[Path] = None, clock=None) -> None:
        import time

        self._projects_dir = projects_dir
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._entries: "OrderedDict[str, _Entry]" = OrderedDict()

    def tally(
        self,
        family: Optional[str],
        conversation_uuid: Optional[str],
        working_dir: Optional[str],
        process_started_at: Optional[datetime],
        now: Optional[datetime] = None,
    ) -> SubagentTally:
        if family is not None and family != DEFAULT_FAMILY:
            return NOT_APPLICABLE
        if not conversation_uuid:
            return ABSENT
        try:
            return self._tally(conversation_uuid, working_dir, process_started_at,
                               now or datetime.now(timezone.utc))
        except OSError as exc:
            logger.debug("subagent_tally_unreadable", error=str(exc),
                         error_type=type(exc).__name__)
            return UNCHECKED

    def transcript_path(self, conversation_uuid: Optional[str],
                        working_dir: Optional[str]) -> Optional[Path]:
        if not conversation_uuid:
            return None
        try:
            return self._entry_for(conversation_uuid, working_dir, self._clock()).path
        except OSError as exc:
            logger.debug("subagent_transcript_unlocated", error=str(exc))
            return None

    def _entry_for(self, uuid: str, working_dir: Optional[str], at: float) -> _Entry:
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
                entry.tally = ABSENT if location.outcome == CONVERSATION_ABSENT else UNCHECKED
                entry.computed_at = at
            with self._lock:
                self._entries[uuid] = entry
                self._entries.move_to_end(uuid)
                while len(self._entries) > MAX_ENTRIES:
                    self._entries.popitem(last=False)
        return entry

    @staticmethod
    def _inputs(parent: Path) -> Tuple[Optional[tuple], bool]:
        directory = subagents_dir_for(parent)
        files, read_now = agent_files_signature_read(directory)
        if files is None:
            return None, read_now
        return (files, index_snapshot(read_completion_index(parent))), read_now

    def _tally(self, uuid: str, working_dir: Optional[str],
               process_started_at: Optional[datetime], now: datetime) -> SubagentTally:
        at = self._clock()
        entry = self._entry_for(uuid, working_dir, at)
        if entry.path is None:
            return entry.tally or UNCHECKED
        key = (_mtime_key(entry.path), _mtime_key(subagents_dir_for(entry.path)),
               process_started_at)
        fresh = entry.tally is not None and at - entry.computed_at < REFRESH_SECONDS
        if fresh and entry.key == key:
            return entry.tally
        inputs, read_now = self._inputs(entry.path)
        if fresh and inputs is not None and inputs == entry.inputs and key[2] == entry.key[2]:
            entry.key = key
            return entry.tally
        if inputs is not None and not read_now:
            current = read_agent_files_signature(subagents_dir_for(entry.path))
            inputs = None if current is None else (current, inputs[1])
        result = read_marked(entry.path, conversation_uuid=uuid,
                             process_started_at=process_started_at, now=now,
                             files=inputs[0] if inputs is not None else None)
        counts = result.counts
        if result.state != STATE_OK or counts is None:
            tally = UNCHECKED
        else:
            latest = max(
                (at for at in (parse_timestamp(row.last_activity_at)
                               for row in result.subagents) if at is not None),
                default=None,
            )
            stalled = stalled_agents(result)
            limit = STALL_NOTIFY_AFTER.total_seconds()
            tally = SubagentTally(
                STATE_OK, running=counts.running, total=counts.total, unknown=counts.unknown,
                last_activity_at=latest, stalled=len(stalled),
                long_stalled=tuple(a for a in stalled if a.idle_seconds >= limit))
        entry.key, entry.tally, entry.computed_at, entry.inputs = key, tally, at, inputs
        return tally


__all__ = [
    "SubagentTally", "SubagentTallyCache", "process_start_for",
    "NOT_APPLICABLE", "UNCHECKED", "ABSENT", "REFRESH_SECONDS", "MAX_ENTRIES",
]
