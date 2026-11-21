
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

import structlog

from src.core.pack.jobs import place, policy as policy_mod, precheck_learn
from src.core.pack.jobs.precheck_hook import expects_long, is_heavy
from src.core.pack.jobs.types import JobError
from src.core.pack.placement import workload
from src.core.pack.reserve.holds import Holds

logger = structlog.get_logger()

HERE_WINDOW_S = 120.0
START_WINDOW_S = 6 * 3600.0
_MAX_KEPT = 512


@dataclass(frozen=True)
class Verdict:

    decision: str
    reason: str = ""
    computer: Optional[str] = None


class Memory:

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._here: Dict[str, float] = {}
        self._started: Dict[Tuple[str, str], Tuple[float, str, str]] = {}

    def _trim(self, table: Dict, window: float, stamp: Callable = lambda v: v) -> None:
        now = self._clock()
        for key in [k for k, v in table.items() if now - stamp(v) > window]:
            del table[key]
        for key in sorted(table, key=lambda k: stamp(table[k]))[:max(0, len(table) - _MAX_KEPT)]:
            del table[key]

    def note_here(self, session: str) -> None:
        with self._lock:
            self._here[session] = self._clock()
            self._trim(self._here, HERE_WINDOW_S)

    def lets_through(self, session: str) -> bool:
        with self._lock:
            return self._clock() - self._here.get(session, float("-inf")) <= HERE_WINDOW_S

    def note_start(self, session: str, tool_use_id: str, project_uid: str, command_shape: str) -> None:
        with self._lock:
            self._started[(session, tool_use_id)] = (self._clock(), project_uid, command_shape)
            self._trim(self._started, START_WINDOW_S, stamp=lambda v: v[0])

    def pop_start(self, session: str, tool_use_id: str) -> Optional[Tuple[float, str, str]]:
        with self._lock:
            entry = self._started.pop((session, tool_use_id), None)
        return None if entry is None else (self._clock() - entry[0], entry[1], entry[2])


MEMORY = Memory()


def finished(engine, session: str, tool_use_id: str, *, memory: Memory = MEMORY) -> None:
    seen = memory.pop_start(session, tool_use_id)
    if seen is None:
        return
    seconds, project_uid, command_shape = seen
    try:
        precheck_learn.record(engine.store, project_uid, command_shape, seconds)
    except Exception as exc:  # noqa: BLE001
        logger.warning("precheck_record_failed", error_type=type(exc).__name__, error=str(exc))


def decide(engine, session: str, command: str, folder: str, *, tool_use_id: str = "", background: bool = False,
           timeout_ms: Optional[int] = None, memory: Memory = MEMORY) -> Verdict:
    try:
        project, _why = engine._resolve_project(folder)  # noqa: SLF001
        if project is None:
            return Verdict("run")
        pol = policy_mod.get(engine.store, project["uid"])
        if not pol.auto_delegate:
            return Verdict("run")
        command_shape = precheck_learn.shape(command)
        if tool_use_id and command_shape:
            memory.note_start(session, tool_use_id, project["uid"], command_shape)
        heavy = is_heavy(command) or expects_long(command, background, timeout_ms) or precheck_learn.learned_heavy(engine.store, project["uid"], command_shape)
        if not heavy or memory.lets_through(session):
            return Verdict("run")
        view = engine._view_for(project["root"], project["uid"])  # noqa: SLF001
        answer = place.place(workload.resolve({"kind": workload.KIND_LIGHT}), project["uid"], pol, view, holds=Holds())
    except JobError:
        return Verdict("run")
    except Exception as exc:  # noqa: BLE001
        logger.warning("precheck_failed", error_type=type(exc).__name__, error=str(exc))
        return Verdict("run")
    if answer.decision != "remote":
        return Verdict("run")
    return Verdict("block", answer.reason, answer.peer_label)


def decide_agent(engine, session: str, folder: str, *, memory: Memory = MEMORY) -> Verdict:
    try:
        project, _why = engine._resolve_project(folder)  # noqa: SLF001
        if project is None:
            return Verdict("run")
        pol = policy_mod.get(engine.store, project["uid"])
        if not pol.auto_delegate or memory.lets_through(session):
            return Verdict("run")
        view = engine._view_for(project["root"], project["uid"])  # noqa: SLF001
        answer = place.place(workload.resolve({"kind": workload.KIND_LIGHT}), project["uid"], pol, view, holds=Holds())
    except JobError:
        return Verdict("run")
    except Exception as exc:  # noqa: BLE001
        logger.warning("precheck_agent_failed", error_type=type(exc).__name__, error=str(exc))
        return Verdict("run")
    if answer.decision != "remote":
        return Verdict("run")
    return Verdict("block", answer.reason, answer.peer_label)
