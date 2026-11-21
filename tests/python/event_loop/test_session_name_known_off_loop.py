
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from src.api.session_name_known import known_tmux_names_async
from tests.python.event_loop.loop_stall import MAX_LOOP_STALL_SECONDS, max_stall_while

PROBE_SECONDS = 0.6


class _SlowManager:

    def active_tmux_names(self) -> set[str]:
        return {"live"}

    def list_attachable_sessions(self) -> list:
        time.sleep(PROBE_SECONDS)
        return []


@pytest.mark.asyncio
async def test_known_names_probe_does_not_block_the_loop() -> None:
    result: dict[str, set[str]] = {}

    async def run() -> None:
        result["names"] = await known_tmux_names_async(
            _SlowManager(), SimpleNamespace(names={"owned"})
        )

    stall = await max_stall_while(run())
    assert result["names"] == {"owned", "live"}
    assert stall < MAX_LOOP_STALL_SECONDS, f"loop stalled {stall:.2f}s"


class _GuardedNames:

    threads: list = []

    def __init__(self, *names: str) -> None:
        self._names = names

    def __iter__(self):  # type: ignore[no-untyped-def]
        import threading

        _GuardedNames.threads.append(threading.current_thread())
        return iter(self._names)


@pytest.mark.asyncio
async def test_thread_never_touches_owned_container() -> None:
    import threading

    _GuardedNames.threads = []
    names = await known_tmux_names_async(_SlowManager(), SimpleNamespace(names=_GuardedNames("owned")))
    assert names == {"owned", "live"}
    assert _GuardedNames.threads, "the guard saw no iteration"
    assert all(t is threading.main_thread() for t in _GuardedNames.threads)
