
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest

from src.api.resize_negotiation import apply_effective_size
from src.core.terminal_size import TerminalSizeNegotiator


class _StubTmuxManager:

    def __init__(self) -> None:
        self.running = 0
        self.max_running = 0
        self.applied: list[tuple[int, int]] = []
        self.guard = threading.Lock()

    def resize_terminal(self, cols: int, rows: int, session_id: str | None = None) -> None:
        with self.guard:
            self.running += 1
            self.max_running = max(self.max_running, self.running)
        time.sleep(0.3)
        with self.guard:
            self.running -= 1
            self.applied.append((cols, rows))


class _Connections:
    async def broadcast_to_session(self, *a: Any, **k: Any) -> None:
        return None


@pytest.mark.asyncio
async def test_cancelled_caller_does_not_overlap_the_next_resize() -> None:
    manager = _StubTmuxManager()
    negotiator = TerminalSizeNegotiator()
    conns = _Connections()

    first = asyncio.ensure_future(apply_effective_size(manager, "ses_c", negotiator, (100, 30), conns))
    await asyncio.sleep(0.1)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    await apply_effective_size(manager, "ses_c", negotiator, (120, 40), conns)
    await asyncio.sleep(0.4)

    assert manager.max_running == 1
    assert manager.applied[-1] == (120, 40)
