
from __future__ import annotations

import asyncio
import atexit
import contextvars
import functools
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional, TypeVar

T = TypeVar("T")

_lock = threading.Lock()
_pools: dict[str, ThreadPoolExecutor] = {}


def interactive_max_workers() -> int:
    return max(16, (os.cpu_count() or 4) * 2)


def configure_default_executor(loop: asyncio.AbstractEventLoop) -> None:
    old = getattr(loop, "_default_executor", None)
    want = interactive_max_workers()
    if isinstance(old, ThreadPoolExecutor) and getattr(old, "_max_workers", 0) >= want:
        return
    loop.set_default_executor(ThreadPoolExecutor(max_workers=want, thread_name_prefix="interactive"))
    if isinstance(old, ThreadPoolExecutor):
        old.shutdown(wait=False)


def _pool(name: str, max_workers: int) -> ThreadPoolExecutor:
    with _lock:
        pool = _pools.get(name)
        if pool is None or getattr(pool, "_shutdown", False):
            pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=name)
            _pools[name] = pool
        return pool


def attention_executor() -> ThreadPoolExecutor:
    return _pool("attention-reader", 4)


def precheck_executor() -> ThreadPoolExecutor:
    return _pool("git-precheck", 4)


def maintenance_executor() -> ThreadPoolExecutor:
    return _pool("bg-maintenance", 2)


async def run_in(executor: Optional[ThreadPoolExecutor], fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    call = functools.partial(ctx.run, fn, *args, **kwargs)
    return await loop.run_in_executor(executor, call)


def shutdown_all() -> None:
    with _lock:
        pools = list(_pools.values())
        _pools.clear()
    for pool in pools:
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            pool.shutdown(wait=False)


atexit.register(shutdown_all)
