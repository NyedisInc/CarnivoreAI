
from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from src.api.resize_negotiation import apply_effective_size
from src.core.tmux_transport.lifecycle import RESIZE_TIMEOUT_SECONDS, LocalLifecycle
from tests.python.event_loop.loop_stall import MAX_LOOP_STALL_SECONDS, max_stall_while

PROBE_SECONDS = 0.3


class _SlowResizeManager:

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def resize_terminal(self, cols: int, rows: int, session_id: str | None = None) -> None:
        time.sleep(PROBE_SECONDS)
        self.calls.append((cols, rows))


class _Connections:

    async def broadcast_to_session(self, *a: Any, **k: Any) -> None:
        return None


@pytest.mark.asyncio
async def test_negotiated_resize_does_not_block_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _SlowResizeManager()

    async def no_broadcast(*a: Any, **k: Any) -> None:
        return None

    monkeypatch.setattr("src.api.resize_negotiation.broadcast_size", no_broadcast)
    outcome: dict[str, Any] = {}

    async def run() -> None:
        outcome["r"] = await apply_effective_size(
            manager, "ses_1", None, (100, 30), _Connections()  # type: ignore[arg-type]
        )

    stall = await max_stall_while(run())
    assert manager.calls == [(100, 30)]
    assert outcome["r"] == (True, False)
    assert stall < MAX_LOOP_STALL_SECONDS, f"loop stalled {stall:.2f}s"


def test_local_resize_passes_a_timeout() -> None:
    seen: list[dict[str, Any]] = []

    class _Backend:
        tmux_session = "cloude_x"

        def _run_tmux_sync(self, *args: str, **kwargs: Any) -> tuple[int, bytes, bytes]:
            seen.append(kwargs)
            return (0, b"", b"")

    LocalLifecycle(_Backend()).resize(80, 24)  # type: ignore[arg-type]
    assert len(seen) == 2
    assert all(k.get("timeout") == RESIZE_TIMEOUT_SECONDS for k in seen)


@pytest.mark.asyncio
async def test_concurrent_resizes_apply_in_negotiated_order(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _SlowResizeManager()

    async def no_broadcast(*a: Any, **k: Any) -> None:
        return None

    monkeypatch.setattr("src.api.resize_negotiation.broadcast_size", no_broadcast)
    sizes = [(100, 30), (90, 28), (80, 24)]
    await asyncio.gather(*(
        apply_effective_size(manager, "ses_1", None, size, _Connections())  # type: ignore[arg-type]
        for size in sizes
    ))
    assert manager.calls == sizes


def test_local_resize_timeout_logs_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    from src.core.tmux_transport import lifecycle

    class _Backend:
        tmux_session = "cloude_x"

        def _run_tmux_sync(self, *args: str, **kwargs: Any) -> tuple[int, bytes, bytes]:
            raise subprocess.TimeoutExpired(cmd="tmux", timeout=RESIZE_TIMEOUT_SECONDS)

    events: list[tuple[str, dict[str, Any]]] = []

    class _Log:
        def warning(self, event: str, **kw: Any) -> None:
            events.append((event, kw))

        def debug(self, event: str, **kw: Any) -> None:
            events.append((f"debug:{event}", kw))

    monkeypatch.setattr(lifecycle, "logger", _Log())
    LocalLifecycle(_Backend()).resize(90, 33)  # type: ignore[arg-type]
    assert [e for e, _ in events] == ["tmux_resize_timeout"]
    assert (events[0][1]["session"], events[0][1]["cols"], events[0][1]["rows"]) == ("cloude_x", 90, 33)
