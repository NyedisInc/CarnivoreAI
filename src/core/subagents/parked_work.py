
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

import structlog

from src.core.agent_families import DEFAULT_FAMILY
from src.core.attention.output_holders import HELD, UNMEASURED, probe_output_holders
from src.core.attention.registry_record import REG_IDLE, REG_OK, REG_SHELL
from src.core.attention.turn_counts import KIND_SHELL
from src.core.subagents.parent_index import read_completion_index
from src.core.subagents.reader import subagents_dir_for
from src.core.subagents.scan_inputs import agent_files_signature, index_snapshot
from src.core.subagents.parked_launches import (
    OpenLaunches,
    find_open_launches,
    newest_real_prompt,
)

logger = structlog.get_logger(__name__)

PARKED_NONE: str = "none"
PARKED_LIVE: str = "live"
PARKED_UNMEASURED: str = "unmeasured"

REFRESH_SECONDS: float = 10.0

MAX_ENTRIES: int = 256


MAX_WIRE_ENTRIES: int = 20


@dataclass(frozen=True)
class ParkedEntry:

    agent_id: str
    task_id: str
    kind: str
    started_at: Optional[datetime]
    live: bool
    agent_type: Optional[str] = None
    description: Optional[str] = None


def _duration_words(seconds: float) -> str:
    minutes = max(1, int((max(0.0, seconds) + 59) // 60))
    if minutes < 60:
        return "%dm" % minutes
    hours = minutes // 60
    if hours < 24:
        return "%dh" % hours
    return "%dd" % (hours // 24)


def describe_entry(entry: "ParkedEntry", *, now: datetime) -> str:
    kind_word = "shell" if entry.kind == KIND_SHELL else "monitor"
    owner = entry.description or entry.agent_type or ("agent " + entry.agent_id[:8])
    if entry.started_at is not None:
        age = _duration_words((now - entry.started_at).total_seconds())
    else:
        age = "an unknown time"
    verb = "running" if entry.live else "open (not confirmed running) for"
    return "background %s %s from sub-agent '%s', %s %s" % (
        kind_word, entry.task_id, owner, verb, age)


@dataclass(frozen=True)
class ParkedWork:

    state: str
    live: int = 0
    unmeasured: int = 0
    detail: str = ""

    entries: Tuple[ParkedEntry, ...] = ()

    @property
    def is_live(self) -> bool:
        return self.state == PARKED_LIVE

    @property
    def is_unmeasured(self) -> bool:
        return self.state == PARKED_UNMEASURED


NOTHING = ParkedWork(PARKED_NONE)


def _stamp(value: Optional[datetime]) -> str:
    return value.strftime("%H:%M:%SZ") if value is not None else "an undated moment"


def judge(
    open_launches: OpenLaunches,
    *,
    claude_pid: Optional[int],
    process_parents: Callable[[], Optional[Mapping[int, int]]],
) -> ParkedWork:
    launches = open_launches.launches
    if not launches:
        return NOTHING
    shells = [l for l in launches if l.kind == KIND_SHELL and l.output_path]
    answers: Dict[str, str] = {}
    if shells:
        answers = probe_output_holders(
            [l.output_path for l in shells], root_pid=claude_pid,
            process_parents=process_parents(),
        )
    live = [l for l in shells if answers.get(l.output_path) == HELD]
    unmeasured = [l for l in launches if l.kind != KIND_SHELL or not l.output_path
                  or answers.get(l.output_path) == UNMEASURED]
    since = _stamp(open_launches.since)
    entries = tuple(
        ParkedEntry(agent_id=l.agent_id, task_id=l.task_id, kind=l.kind,
                    started_at=l.launched_at, live=is_live,
                    agent_type=l.agent_type, description=l.description)
        for is_live, group in ((True, live), (False, unmeasured))
        for l in group
    )[:MAX_WIRE_ENTRIES]
    if live:
        first = live[0]
        return ParkedWork(PARKED_LIVE, len(live), len(unmeasured), (
            "sub-agent %s acted at %s, after the last prompt at %s, and is parked "
            "on background shell %s, whose output file a live child of this "
            "claude holds open (%d such task(s))"
            % (first.agent_id, _stamp(first.owner_active_at), since,
               first.task_id, len(live))), entries=entries)
    if unmeasured:
        first = unmeasured[0]
        why = ("a Monitor keeps its output on pipes to claude, so no process "
               "holds its file" if first.kind != KIND_SHELL
               else "its output file could not be probed")
        return ParkedWork(PARKED_UNMEASURED, 0, len(unmeasured), (
            "sub-agent %s acted at %s, after the last prompt at %s, and left "
            "background %s %s open, which could not be measured running or "
            "ended: %s" % (first.agent_id, _stamp(first.owner_active_at), since,
                           first.kind, first.task_id, why)), entries=entries)
    return NOTHING


@dataclass
class _Entry:

    key: Tuple
    launches: OpenLaunches
    until: float
    state: str = PARKED_NONE
    inputs: Optional[tuple] = None


class ParkedWorkReader:

    def __init__(self, *, clock: Optional[Callable[[], float]] = None) -> None:
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._entries: Dict[str, _Entry] = {}

    def read(
        self,
        family: Optional[str],
        parent_path: Optional[Path],
        registry: Any,
        facts: Any,
        now: datetime,
        *,
        process_started_at: Optional[datetime],
        process_parents: Callable[[], Optional[Mapping[int, int]]],
    ) -> Optional[ParkedWork]:
        if family is not None and family != DEFAULT_FAMILY:
            return None
        if parent_path is None or getattr(registry, "verdict", None) != REG_OK:
            return None
        if getattr(registry, "status", None) not in (REG_IDLE, REG_SHELL):
            return None
        try:
            launches = self._launches(parent_path, facts, process_started_at, now)
            result = judge(launches, claude_pid=getattr(registry, "pid", None),
                           process_parents=process_parents)
        except OSError as exc:
            logger.warning("parked_work_unreadable", path=str(parent_path), error=str(exc))
            return None
        self._log_transition(str(parent_path), result)
        return result

    def _launches(self, parent_path: Path, facts: Any,
                  process_started_at: Optional[datetime], now: datetime) -> OpenLaunches:
        prompt = newest_real_prompt(parent_path)
        window = getattr(facts, "newest_user_prompt_at", None)
        if window is not None and (prompt is None or window > prompt):
            prompt = window
        key = (_mtime(parent_path), _mtime(parent_path.with_suffix("") / "subagents"),
               prompt, process_started_at)
        at = self._clock()
        with self._lock:
            entry = self._entries.get(str(parent_path))
        if entry is not None and entry.key == key and at < entry.until:
            if _deadline_open(entry.launches, now):
                return entry.launches
        inputs = (prompt, process_started_at, agent_files_signature(subagents_dir_for(parent_path)),
                  index_snapshot(read_completion_index(parent_path)))
        if (entry is not None and inputs == entry.inputs and inputs[2] is not None
                and _deadline_open(entry.launches, now)):
            with self._lock:
                entry.key, entry.until = key, at + REFRESH_SECONDS
            return entry.launches
        launches = find_open_launches(parent_path, last_prompt_at=prompt,
                                      process_started_at=process_started_at, now=now)
        with self._lock:
            old = self._entries.pop(str(parent_path), None)
            self._entries[str(parent_path)] = _Entry(
                key, launches, at + REFRESH_SECONDS, old.state if old else PARKED_NONE, inputs)
            while len(self._entries) > MAX_ENTRIES:
                self._entries.pop(next(iter(self._entries)))
        return launches

    def _log_transition(self, path: str, result: ParkedWork) -> None:
        with self._lock:
            entry = self._entries.get(path)
            if entry is None or entry.state == result.state:
                return
            entry.state = result.state
        if result.is_unmeasured:
            logger.warning("parked_work_unmeasured", path=path, detail=result.detail)
        else:
            logger.info("parked_work_state", path=path, state=result.state,
                        live=result.live, detail=result.detail)


def _deadline_open(launches: OpenLaunches, now: datetime) -> bool:
    deadline = launches.earliest_deadline
    return deadline is None or deadline > now


def _mtime(path: Path) -> Optional[Tuple[int, int]]:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_size, stat.st_mtime_ns)


__all__ = [
    "ParkedWork", "ParkedEntry", "ParkedWorkReader", "judge", "describe_entry",
    "NOTHING", "PARKED_NONE", "PARKED_LIVE", "PARKED_UNMEASURED",
    "MAX_WIRE_ENTRIES",
]
