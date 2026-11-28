
from __future__ import annotations

import asyncio
import contextvars
import functools
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional, TypeVar

from src.core.pack.machines import capabilities

T = TypeVar("T")

_EXECUTOR: Optional[ThreadPoolExecutor] = None
_LOCK = threading.Lock()


def _executor() -> ThreadPoolExecutor:
    global _EXECUTOR
    with _LOCK:
        if _EXECUTOR is None:
            _EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="peer-import")
        return _EXECUTOR


async def run(fn: Callable[..., T], *args: Any) -> T:
    if not capabilities.mesh_on():
        return await asyncio.to_thread(fn, *args)
    context = contextvars.copy_context()
    return await asyncio.get_running_loop().run_in_executor(_executor(), functools.partial(context.run, fn, *args))
