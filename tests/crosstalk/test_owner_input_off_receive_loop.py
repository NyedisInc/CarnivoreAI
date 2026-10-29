
import asyncio
import time
from types import SimpleNamespace

from fastapi import WebSocketDisconnect

from src.api import ws_receive
from src.core.crosstalk import contacts


class _Socket:

    def __init__(self) -> None:
        self.app = SimpleNamespace()
        self.scope = {}
        self._frames = [{"bytes": b"a"}, {"bytes": b"b"}]

    async def receive(self) -> dict:
        if self._frames:
            return self._frames.pop(0)
        raise WebSocketDisconnect()


def test_keystroke_not_blocked_by_slow_owner_input(monkeypatch) -> None:
    calls: list[str] = []
    writes: list[tuple[str, float]] = []

    async def slow_owner_input(app, session_id):
        calls.append(session_id)
        await asyncio.sleep(2)

    class Manager:
        async def send_input(self, text, session_id=None):
            writes.append((text, time.monotonic()))

    monkeypatch.setattr(contacts, "owner_input", slow_owner_input)

    async def run() -> float:
        start = time.monotonic()
        try:
            await ws_receive.receive_messages(_Socket(), Manager(), session_id="ses_x")
        except WebSocketDisconnect:
            pass
        elapsed = time.monotonic() - start
        await asyncio.sleep(0.05)
        for t in list(contacts._tasks):
            t.cancel()
        await asyncio.gather(*contacts._tasks, return_exceptions=True)
        return elapsed

    elapsed = asyncio.run(run())
    assert "".join(w[0] for w in writes) == "ab"
    assert elapsed < 0.2, f"receive loop waited {elapsed:.3f}s on owner_input"
    assert calls == ["ses_x"], "second keystroke must coalesce into the in-flight run"
    assert not contacts._in_flight


def test_schedule_is_guarded_per_pane(monkeypatch) -> None:
    started: list[str] = []

    async def slow(app, session_id):
        started.append(session_id)
        await asyncio.sleep(0.05)

    monkeypatch.setattr(contacts, "owner_input", slow)

    async def run() -> list[bool]:
        got = [contacts.schedule_owner_input(None, "p1"), contacts.schedule_owner_input(None, "p1"),
               contacts.schedule_owner_input(None, "p2")]
        await asyncio.gather(*contacts._tasks)
        got.append(contacts.schedule_owner_input(None, "p1"))
        await asyncio.gather(*contacts._tasks)
        return got

    assert asyncio.run(run()) == [True, False, True, True]
    assert started == ["p1", "p2", "p1"]
