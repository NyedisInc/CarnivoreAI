
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List

import pytest

from src.core.pane_tail.tail_supervisor import MAX_BACKOFF_SECONDS, next_backoff, supervise_tail
from src.core.tmux_backend import TmuxBackend


def test_backoff_doubles_and_is_capped() -> None:
    steps, pause = [], 0.0
    for _ in range(10):
        pause = next_backoff(pause)
        steps.append(pause)
    assert steps[:3] == [0.5, 1.0, 2.0] and max(steps) == MAX_BACKOFF_SECONDS


def test_a_failing_tail_is_run_again_until_the_backend_stops() -> None:
    runs: List[int] = []
    pauses: List[float] = []
    state = {"running": True}

    async def run_once() -> None:
        runs.append(1)
        if len(runs) <= 2:
            raise OSError("pipe went away")
        if len(runs) == 3:
            return
        state["running"] = False

    async def fake_sleep(seconds: float) -> None:
        pauses.append(seconds)

    asyncio.run(supervise_tail(run_once, is_running=lambda: state["running"], session="s", sleep=fake_sleep))
    assert len(runs) == 4 and pauses == [0.5, 1.0, 2.0]


def test_a_programming_error_surfaces_instead_of_looping() -> None:
    async def run_once() -> None:
        raise TypeError("bug")

    with pytest.raises(TypeError):
        asyncio.run(supervise_tail(run_once, is_running=lambda: True, session="s"))


def test_the_backend_tail_survives_a_crash_and_keeps_reading(tmp_path: Path, monkeypatch) -> None:
    pipe = tmp_path / "pipe.log"
    pipe.touch()
    seen: List[bytes] = []
    backend = TmuxBackend(session_id="tailsup", working_dir=tmp_path, on_output=seen.append,
                          socket_name="unused", session_name="tailsup")
    backend._pipe_path = pipe
    backend._running = True
    calls = {"n": 0}

    async def flaky_rotate(path, fd) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("stat failed")

    monkeypatch.setattr(backend, "_maybe_rotate", flaky_rotate)

    async def drive() -> None:
        task = asyncio.create_task(backend._tail_loop())
        await asyncio.sleep(2.4)
        with pipe.open("ab") as handle:
            handle.write(b"after-the-crash")
        await asyncio.sleep(1.0)
        backend._running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(drive())
    assert calls["n"] >= 2
    assert b"after-the-crash" in b"".join(seen)
