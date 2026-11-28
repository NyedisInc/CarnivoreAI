
from __future__ import annotations

import asyncio
import collections.abc
import contextvars
import functools
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.core.perf_hooks import call_counter

TOP_ROWS = 25

_lock = threading.Lock()
_stats: Dict[Tuple[str, str], List[float]] = {}
_saved_factories: Dict[int, Optional[Callable[..., Any]]] = {}
_installed_loops: "set[int]" = set()


def label(func: Any) -> str:
    for _ in range(4):
        if isinstance(func, functools.partial):
            inner = func.func
            if getattr(inner, "__name__", "") == "run" and isinstance(getattr(inner, "__self__", None), contextvars.Context) and func.args:
                func = func.args[0]
            else:
                func = inner
        elif isinstance(func, functools.partialmethod) or not hasattr(func, "__func__"):
            break
        else:
            func = func.__func__
    name = getattr(func, "__qualname__", None) or getattr(func, "__name__", None) or type(func).__name__
    return f"{getattr(func, '__module__', None) or '?'}.{name}"


def _record(kind: str, name: str, cpu: float) -> None:
    if not call_counter.is_active():
        return
    with _lock:
        row = _stats.setdefault((kind, name), [0, 0.0])
        row[0] += 1
        row[1] += cpu


class _CountingExecutor(ThreadPoolExecutor):

    def submit(self, fn, /, *args, **kwargs):  # noqa: D401
        if not call_counter.is_active():
            return super().submit(fn, *args, **kwargs)
        name = label(fn)

        def timed():
            t0 = time.thread_time()
            try:
                return fn(*args, **kwargs)
            finally:
                _record("executor", name, time.thread_time() - t0)

        return super().submit(timed)


class _TimedCoroutine(collections.abc.Coroutine):

    __slots__ = ("_coro", "_name")

    def __init__(self, coro: Any) -> None:
        self._coro = coro
        self._name = label(coro) if not hasattr(coro, "cr_code") else f"{coro.cr_code.co_filename.rsplit('/', 1)[-1]}:{coro.__qualname__}"

    def send(self, value):
        t0 = time.thread_time()
        try:
            return self._coro.send(value)
        finally:
            _record("task", self._name, time.thread_time() - t0)

    def throw(self, *args):
        t0 = time.thread_time()
        try:
            return self._coro.throw(*args)
        finally:
            _record("task", self._name, time.thread_time() - t0)

    def close(self) -> None:
        self._coro.close()

    def __await__(self):
        return self._coro.__await__()

    def __getattr__(self, item: str) -> Any:
        return getattr(self._coro, item)


def attach(loop: asyncio.AbstractEventLoop) -> bool:
    if id(loop) in _saved_factories:
        return False
    if id(loop) not in _installed_loops:
        from src.core.perf_hooks.executors import interactive_max_workers  # noqa: PLC0415

        old = getattr(loop, "_default_executor", None)
        loop.set_default_executor(_CountingExecutor(max_workers=interactive_max_workers(), thread_name_prefix="counted"))
        if isinstance(old, ThreadPoolExecutor):
            old.shutdown(wait=False)
        _installed_loops.add(id(loop))
    previous = loop.get_task_factory()
    _saved_factories[id(loop)] = previous

    def factory(lp, coro, **kwargs):
        if call_counter.is_active() and asyncio.iscoroutine(coro):
            coro = _TimedCoroutine(coro)
        return previous(lp, coro, **kwargs) if previous is not None else asyncio.Task(coro, loop=lp, **kwargs)

    loop.set_task_factory(factory)
    return True


def detach(loop: asyncio.AbstractEventLoop) -> None:
    if id(loop) in _saved_factories:
        loop.set_task_factory(_saved_factories.pop(id(loop)))


def reset() -> None:
    with _lock:
        _stats.clear()


def report(seconds: float) -> Dict[str, List[Dict[str, Any]]]:
    with _lock:
        items = list(_stats.items())
        _stats.clear()
    out: Dict[str, List[Dict[str, Any]]] = {"executor_jobs": [], "loop_tasks": []}
    for (kind, name), (count, cpu) in sorted(items, key=lambda kv: -kv[1][1]):
        rows = out["executor_jobs" if kind == "executor" else "loop_tasks"]
        if len(rows) < TOP_ROWS:
            rows.append({
                "function": name, "count": int(count), "per_second": round(count / seconds, 3) if seconds > 0 else None,
                "cpu_ms": round(cpu * 1000, 3), "cpu_us_per_call": round(cpu * 1e6 / count, 1) if count else None,
            })
    return out
