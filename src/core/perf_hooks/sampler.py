
from __future__ import annotations

import functools
import gc
import os
import sys
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.perf_hooks import call_counter
from src.core.perf_hooks.call_counter import thread_group
from src.core.perf_hooks.thread_cpu import ThreadCpu, read_thread_cpu

logger = structlog.get_logger()

MAX_SECONDS = 120.0
MIN_SECONDS = 1.0
MAX_HZ = 250
MIN_HZ = 1
DEFAULT_HZ = 100
DEFAULT_TOP = 25
MAX_TOP = 100
STACK_DEPTH = 24
_PARKED_LEAVES = frozenset({
    "select", "wait", "get", "_worker", "sleep", "accept", "recv", "poll", "control", "_wait_for_tstate_lock",
})

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))) + os.sep
_STDLIB = os.path.dirname(os.__file__) + os.sep
_running = threading.Lock()


class ProfileBusyError(Exception):
    """A profile is already running; only one runs at a time."""


@dataclass(frozen=True)
class ProfileRequest:

    seconds: float = 30.0
    hz: int = DEFAULT_HZ
    top: int = DEFAULT_TOP


@functools.lru_cache(maxsize=8192)
def frame_label(filename: str, func: str, line: Optional[int] = None) -> str:
    if filename.startswith(_REPO_ROOT):
        path = filename[len(_REPO_ROOT):]
    elif "site-packages" + os.sep in filename:
        path = filename.split("site-packages" + os.sep, 1)[1]
    elif _STDLIB != os.sep and filename.startswith(_STDLIB):
        path = "stdlib/" + filename[len(_STDLIB):]
    else:
        path = os.path.basename(filename)
    return f"{path}:{func}" if line is None else f"{path}:{func}:{line}"


def _stack(frame: Any) -> Tuple[Tuple[str, str, int], ...]:
    out = []
    while frame is not None and len(out) < STACK_DEPTH:
        code = frame.f_code
        out.append((code.co_filename, code.co_name, frame.f_lineno))
        frame = frame.f_back
    return tuple(out)


class _GcTimer:

    def __init__(self) -> None:
        self.started: Dict[int, float] = {}
        self.seconds: Counter = Counter()
        self.count: Counter = Counter()

    def __call__(self, phase: str, info: Dict[str, Any]) -> None:
        ident = threading.get_ident()
        if phase == "start":
            self.started[ident] = time.perf_counter()
            return
        begun = self.started.pop(ident, None)
        if begun is not None:
            generation = info.get("generation", -1)
            self.seconds[generation] += time.perf_counter() - begun
            self.count[generation] += 1

    def report(self) -> List[Dict[str, Any]]:
        return [
            {"generation": g, "collections": self.count[g], "seconds": round(self.seconds[g], 4)}
            for g in sorted(self.count)
        ]


class _Aggregate:

    def __init__(self) -> None:
        self.stacks: Dict[Tuple[str, Tuple[str, ...]], List[float]] = defaultdict(lambda: [0.0, 0])
        self.inclusive: Counter = Counter()
        self.self_time: Counter = Counter()
        self.samples = 0

    def add(self, group: str, stack: Tuple[Tuple[str, str, int], ...], weight: float) -> None:
        if not stack:
            return
        self.samples += 1
        labels = tuple(frame_label(f, fn) for f, fn, _ in stack)
        row = self.stacks[(group, labels)]
        row[0] += weight
        row[1] += 1
        leaf_file, leaf_func, leaf_line = stack[0]
        self.self_time[frame_label(leaf_file, leaf_func, leaf_line)] += weight
        for label in set(labels):
            self.inclusive[label] += weight


def _thread_names() -> Dict[int, Tuple[str, Optional[int]]]:
    return {t.ident: (t.name, t.native_id) for t in threading.enumerate() if t.ident is not None}


def _clamp(request: ProfileRequest) -> ProfileRequest:
    return ProfileRequest(
        seconds=min(MAX_SECONDS, max(MIN_SECONDS, float(request.seconds))),
        hz=min(MAX_HZ, max(MIN_HZ, int(request.hz))),
        top=min(MAX_TOP, max(1, int(request.top))),
    )


BETWEEN_SAMPLES = (("<cpu burned between ticks; thread back at its idle point>", "?", 0),)

Cpu = Optional[Dict[int, ThreadCpu]]


def at_idle_point(stack: Tuple[Tuple[str, str, int], ...]) -> bool:
    if not stack:
        return True
    filename, func, _ = stack[0]
    if func == "_worker" and filename.endswith(os.path.join("concurrent", "futures", "thread.py")):
        return True
    if func == "run" and filename.endswith(os.path.join("asyncio", "runners.py")):
        return True
    return func == "select" and len(stack) > 1 and stack[1][1] == "_run_once"


def _charge(cpu_now: Cpu, cpu_prev: Cpu, native_id: Optional[int],
            frame: Any) -> Tuple[Optional[float], Tuple[Tuple[str, str, int], ...]]:
    if cpu_now is not None and cpu_prev is not None:
        if native_id not in cpu_now:
            return None, ()
        now = cpu_now[native_id]
        before = cpu_prev.get(native_id)
        delta = now.seconds - (before.seconds if before is not None else now.seconds)
        if delta <= 0:
            return None, ()
        stack = _stack(frame)
        return delta, (BETWEEN_SAMPLES if not now.running and at_idle_point(stack) else stack)
    stack = _stack(frame)
    if stack and (stack[0][1] in _PARKED_LEAVES or at_idle_point(stack)):
        return None, ()
    return 1.0, stack


def _sample_loop(request: ProfileRequest, agg: _Aggregate) -> Tuple[Cpu, int]:
    me = threading.get_ident()
    interval = 1.0 / request.hz
    deadline = time.monotonic() + request.seconds
    first = read_thread_cpu()
    cpu_prev = first
    names = _thread_names()
    ticks = 0
    next_tick = time.monotonic()
    while True:
        next_tick += interval
        now = time.monotonic()
        if now >= deadline:
            break
        time.sleep(max(0.0, min(next_tick, deadline) - now))
        cpu_now = read_thread_cpu()
        frames = sys._current_frames()
        if frames.keys() != names.keys():
            names = _thread_names()
        ticks += 1
        for ident, frame in frames.items():
            if ident == me:
                continue
            name, native_id = names.get(ident, (f"thread-{ident}", None))
            weight, stack = _charge(cpu_now, cpu_prev, native_id, frame)
            if weight is not None:
                agg.add(thread_group(name), stack, weight)
        del frames
        cpu_prev = cpu_now if cpu_now is not None else cpu_prev
    return first, ticks


def _per_thread(first: Cpu, last: Cpu, seconds: float, me_native: int, top: int) -> List[Dict[str, Any]]:
    if first is None or last is None:
        return []
    names = {native: name for name, native in _thread_names().values() if native is not None}
    grouped: Dict[str, List[float]] = defaultdict(lambda: [0.0, 0])
    for native, cpu in last.items():
        before = first.get(native)
        delta = cpu.seconds - (before.seconds if before is not None else 0.0)
        if delta <= 0:
            continue
        if native == me_native:
            label = "profiler (this sampler)"
        else:
            label = thread_group(names.get(native, "native (no python thread)"))
        grouped[label][0] += delta
        grouped[label][1] += 1
    rows = sorted(grouped.items(), key=lambda kv: -kv[1][0])[:top]
    return [
        {"thread": label, "threads": int(n), "cpu_seconds": round(cpu, 4),
         "pct_of_core": round(100.0 * cpu / seconds, 2)}
        for label, (cpu, n) in rows
    ]


def _tables(agg: _Aggregate, top: int, by_cpu: bool) -> Dict[str, Any]:
    def fmt(value: float) -> float:
        return round(value, 4) if by_cpu else value

    stacks = sorted(agg.stacks.items(), key=lambda kv: -kv[1][0])[:top]
    return {
        "stacks": [
            {"thread": group, "weight": fmt(w), "samples": n, "frames_leaf_first": list(labels)}
            for (group, labels), (w, n) in stacks
        ],
        "functions_inclusive": [{"function": f, "weight": fmt(w)} for f, w in agg.inclusive.most_common(top)],
        "functions_self": [{"line": f, "weight": fmt(w)} for f, w in agg.self_time.most_common(top)],
    }


def run_profile(request: ProfileRequest) -> Dict[str, Any]:
    request = _clamp(request)
    if not _running.acquire(blocking=False):
        raise ProfileBusyError("a profile is already running")
    gc_timer = _GcTimer()
    agg = _Aggregate()
    try:
        call_counter.start()
        gc.callbacks.append(gc_timer)
        wall0, cpu0 = time.monotonic(), time.process_time()
        try:
            first, ticks = _sample_loop(request, agg)
        finally:
            gc.callbacks.remove(gc_timer)
            wall = time.monotonic() - wall0
            process_cpu = time.process_time() - cpu0
            calls = call_counter.stop(wall)
        last = read_thread_cpu()
        by_cpu = first is not None
        result: Dict[str, Any] = {
            "seconds": round(wall, 3),
            "hz": request.hz,
            "ticks": ticks,
            "weight_unit": "cpu_seconds" if by_cpu else "samples",
            "process_cpu_seconds": round(process_cpu, 4),
            "process_pct_of_core": round(100.0 * process_cpu / wall, 2) if wall > 0 else None,
            "threads": _per_thread(first, last, wall, threading.get_native_id(), request.top),
            **_tables(agg, request.top, by_cpu),
            "calls": calls,
            "gc": gc_timer.report(),
        }
        logger.info("perf_profile_done", seconds=result["seconds"], ticks=ticks,
                    process_pct_of_core=result["process_pct_of_core"], samples=agg.samples)
        return result
    finally:
        _running.release()


async def profile(request: ProfileRequest) -> Dict[str, Any]:
    import asyncio

    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()

    def deliver(outcome: Any, error: Optional[BaseException]) -> None:
        if future.done():
            return
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(outcome)

    def body() -> None:
        try:
            outcome = run_profile(request)
        except Exception as exc:  # noqa: BLE001
            loop.call_soon_threadsafe(deliver, None, exc)
            return
        loop.call_soon_threadsafe(deliver, outcome, None)

    threading.Thread(target=body, name="perf-profiler", daemon=True).start()
    return await future
