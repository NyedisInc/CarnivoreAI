
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.core.notifications.contracts import DeliveryResult, FailureClass, NotifyEvent
from src.core.notifications.routing_view import DestinationView, QuietHours

NOON = datetime(2026, 10, 3, 12, 0).timestamp()
LATE = datetime(2026, 10, 3, 23, 30).timestamp()


def dest(i: int = 1, *, kind: str = "slack", **kw: Any) -> DestinationView:
    return DestinationView(id=f"d_{i:012x}", kind=kind, name=f"dest{i}", enabled=kw.pop("enabled", True),
                           scope="global", config=kw.pop("config", {}), **kw)


class FakeView:

    def __init__(self, dests: List[DestinationView], ticks: Optional[Dict[Tuple[str, str], bool]] = None,
                 paused: bool = False) -> None:
        self.revision = 1
        self.paused = paused
        self.dests = dests
        self.ticks = ticks or {}

    def destinations(self) -> List[DestinationView]:
        return list(self.dests)

    def is_ticked(self, column: str, type_id: str) -> bool:
        return self.ticks.get((column, type_id), True)


class FakeWriter:

    def __init__(self) -> None:
        self.disabled: List[Tuple[str, str]] = []

    async def disable_locally(self, dest_id: str, reason: str) -> None:
        self.disabled.append((dest_id, reason))


class FakeSender:

    def __init__(self, *script: DeliveryResult) -> None:
        self.script = list(script)
        self.calls: List[Tuple[NotifyEvent, Mapping[str, Any], Mapping[str, Any]]] = []

    async def send(self, event, config, secrets):
        self.calls.append((event, config, secrets))
        return self.script.pop(0) if self.script else OK


class Clock:

    def __init__(self, now: float = NOON) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class Sleeper:

    def __init__(self, clock: Clock, manual: bool = False) -> None:
        self.clock = clock
        self.manual = manual
        self.calls: List[float] = []
        self.waiting: List[Tuple[float, asyncio.Future]] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        if self.manual:
            fut = asyncio.get_running_loop().create_future()
            self.waiting.append((seconds, fut))
            await fut
            return
        self.clock.now += seconds
        await asyncio.sleep(0)

    async def release(self, *, advance: bool = True) -> None:
        waiting, self.waiting = self.waiting, []
        if advance and waiting:
            self.clock.now += max(s for s, _ in waiting)
        for _, fut in waiting:
            fut.set_result(None)
        for _ in range(10):
            await asyncio.sleep(0)


class Screens:

    def __init__(self, active: bool = False) -> None:
        self.active = active

    def is_screen_active(self) -> bool:
        return self.active


OK = DeliveryResult(ok=True)


def fail(cls: FailureClass, **kw: Any) -> DeliveryResult:
    return DeliveryResult(ok=False, failure=cls, **kw)


def ev(type_id: str = "session.finished", **kw: Any) -> NotifyEvent:
    ev.n = getattr(ev, "n", 0) + 1
    kw.setdefault("instance_key", f"k{ev.n}")
    kw.setdefault("session_id", f"ses_{ev.n}")
    kw.setdefault("tmux_name", f"cloude_{ev.n}")
    return NotifyEvent(type_id=type_id, kind="Stop", title="t", ts=NOON, **kw)


QUIET_NIGHT = QuietHours("22:00", "07:00")
