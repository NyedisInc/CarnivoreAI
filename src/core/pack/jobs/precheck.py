
from __future__ import annotations

import dataclasses
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

import structlog

from src.core.pack.jobs import engine_agent, load_store, locality, needs_policy, place, policy as policy_mod, precheck_learn
from src.core.pack.jobs.precheck_hook import expects_long, is_heavy
from src.core.pack.jobs.types import JobError, JobRequest
from src.core.pack.placement import workload
from src.core.pack.reserve.holds import HOLDS, Holds

logger = structlog.get_logger()

HERE_WINDOW_S = 600.0
REFUSED_WINDOW_S = 600.0
AGENT_SHAPE = "agent"
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
        self._refused: Dict[Tuple[str, str], float] = {}
        self._let: Dict[Tuple[str, str], float] = {}

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

    def note_delegated(self, session: str) -> None:
        with self._lock:
            for key in [k for k in self._refused if k[0] == session]:
                del self._refused[key]

    def second_try(self, session: str, shape: str) -> str:
        key = (session, shape)
        with self._lock:
            self._trim(self._refused, REFUSED_WINDOW_S)
            self._trim(self._let, REFUSED_WINDOW_S)
            now = self._clock()
            if now - self._let.get(key, float("-inf")) <= REFUSED_WINDOW_S:
                return "let"
            if key in self._refused:
                del self._refused[key]
                self._let[key] = now
                return "gave_way"
            self._refused[key] = now
            return "block"

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


class _ReadOnlyHolds(Holds):

    def total(self, exclude: Optional[str] = None) -> Tuple[float, float, int]:
        return HOLDS.total(exclude)

    def try_hold(self, *args, **kwargs) -> bool:
        return False


def _delegate_kind(command: str) -> str:
    kind = workload.classify_command(command)
    return "suite" if kind == workload.KIND_LIGHT else kind


def _sized_workload(store, project_uid: str, command: str, command_shape: Optional[str], *, agent: bool = False) -> Tuple[workload.Workload, float]:
    if agent:
        work = workload.resolve({"kind": workload.KIND_AGENT})
        return work, workload.est_runtime_s(workload.KIND_AGENT)
    kind = _delegate_kind(command)
    prof = precheck_learn.profile(store, project_uid, command_shape) if store is not None and command_shape else None
    tag: Dict[str, object] = {"kind": kind}
    if prof is not None and prof.p75_cpu_cores is not None:
        tag["est_cpu_cores"] = prof.p75_cpu_cores
    if prof is not None and prof.p75_ram_gb is not None:
        tag["est_ram_gb"] = prof.p75_ram_gb
    work = workload.resolve(tag)
    est_rt = prof.p50_wall_s if prof is not None else workload.est_runtime_s(kind)
    return work, est_rt


def _count_event(store, outcome: str) -> None:
    if store is None:
        return
    try:
        load_store.record_guard_event(store, outcome)
    except Exception:  # noqa: BLE001
        pass


def _placed(engine, project: dict, pol, req: JobRequest, *, agent: bool = False, agent_family: Optional[str] = None,
            work: Optional[workload.Workload] = None, est_runtime_s: Optional[float] = None):
    sized = work if work is not None else workload.resolve({"kind": workload.KIND_AGENT if agent else req.kind})
    view = engine._view_for(project["root"], project["uid"])  # noqa: SLF001
    if view is not None and engine.store is not None:
        try:
            view = dataclasses.replace(view, peer_overheads=load_store.peer_overheads(engine.store, project["uid"]))
        except Exception:  # noqa: BLE001
            pass
    if agent and view is not None:
        view = engine._agent_view(view, family=agent_family)  # noqa: SLF001
    asks = needs_policy.merge(engine.store, project["uid"], req, engine._setup_needs(project["uid"], req.folder, project["root"], pol))  # noqa: SLF001
    ask = {k: v for k, v in (("needs", asks.strict), ("filters", asks.filters), ("prefer", asks.prefer)) if v}
    if est_runtime_s is not None:
        ask["est_runtime_s"] = est_runtime_s
    return place.place(sized, project["uid"], pol, view, holds=_ReadOnlyHolds(), **ask)


def _repeat(engine, memory: Memory, session: str, project_uid: str, shape: str, answer) -> Verdict:
    state = memory.second_try(session, shape)
    if state == "block":
        _count_event(engine.store, "blocked_offload")
        return Verdict("block", answer.reason, answer.peer_label)
    if state == "gave_way":
        logger.info("precheck_gave_way", shape=shape)
        _count_event(engine.store, "gave_way")
        try:
            precheck_learn.record_giveway(engine.store, project_uid, shape)
        except Exception as exc:  # noqa: BLE001
            logger.warning("precheck_giveway_record_failed", error_type=type(exc).__name__, error=str(exc))
    return Verdict("run")


def decide(engine, session: str, command: str, folder: str, *, tool_use_id: str = "", background: bool = False,
           timeout_ms: Optional[int] = None, memory: Memory = MEMORY) -> Verdict:
    try:
        project, _why = engine._resolve_project(folder)  # noqa: SLF001
        if project is None:
            return Verdict("run")
        pol = policy_mod.get(engine.store, project["uid"])
        if not pol.auto_delegate:
            return Verdict("run")
        if locality.local_only_reason(command, folder, project["root"], local_only_globs=getattr(pol, "local_only", ())):
            _count_event(engine.store, "local_only_path")
            return Verdict("run")
        command_shape = precheck_learn.shape(command)
        if tool_use_id and command_shape:
            memory.note_start(session, tool_use_id, project["uid"], command_shape)
        override = load_store.shape_override_get(engine.store, project["uid"], command_shape) if (engine.store and command_shape) else None
        if override == "local_only":
            _count_event(engine.store, "local_only_override")
            return Verdict("run")
        heavy = (override == "always_offload" or is_heavy(command) or expects_long(command, background, timeout_ms)
                 or precheck_learn.learned_heavy(engine.store, project["uid"], command_shape))
        if not heavy or memory.lets_through(session):
            return Verdict("run")
        work, est_rt = _sized_workload(engine.store, project["uid"], command, command_shape)
        answer = _placed(engine, project, pol, JobRequest(command=command, folder=folder, kind=work.kind), work=work, est_runtime_s=est_rt)
        if answer.decision != "remote":
            _count_event(engine.store, "below_breakeven" if "too short" in answer.reason or "overhead" in answer.reason else "local_fit")
            return Verdict("run")
        return _repeat(engine, memory, session, project["uid"], command_shape or "command", answer)
    except JobError:
        return Verdict("run")
    except Exception as exc:  # noqa: BLE001
        logger.warning("precheck_failed", error_type=type(exc).__name__, error=str(exc))
        return Verdict("run")


def decide_agent(engine, session: str, folder: str, *, family: Optional[str] = None, memory: Memory = MEMORY) -> Verdict:
    try:
        project, _why = engine._resolve_project(folder)  # noqa: SLF001
        if project is None:
            return Verdict("run")
        pol = policy_mod.get(engine.store, project["uid"])
        if not pol.auto_delegate or memory.lets_through(session):
            return Verdict("run")
        work, est_rt = _sized_workload(engine.store, project["uid"], "", None, agent=True)
        answer = _placed(engine, project, pol, engine_agent.AgentRequest(command="", folder=folder, kind="suite", task="subagent"),
                         agent=True, agent_family=family, work=work, est_runtime_s=est_rt)
        if answer.decision != "remote":
            return Verdict("run")
        return _repeat(engine, memory, session, project["uid"], AGENT_SHAPE, answer)
    except JobError:
        return Verdict("run")
    except Exception as exc:  # noqa: BLE001
        logger.warning("precheck_agent_failed", error_type=type(exc).__name__, error=str(exc))
        return Verdict("run")
