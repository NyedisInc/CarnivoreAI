
from __future__ import annotations

import asyncio
import threading
import time

from src.core.federation import import_lane
from src.core.pack.machines import capabilities


def test_switch_off_runs_on_the_default_executor_and_switch_on_on_one_lane_thread(monkeypatch):
    spans: list = []

    def work(tag: str):
        start = time.monotonic()
        time.sleep(0.05)
        spans.append((tag, threading.current_thread().name, start, time.monotonic()))
        return tag

    async def both():
        return await asyncio.gather(import_lane.run(work, "a"), import_lane.run(work, "b"))

    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    assert asyncio.run(both()) == ["a", "b"]
    assert all(not name.startswith("peer-import") for _, name, _, _ in spans), spans
    spans.clear()
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    monkeypatch.setattr(import_lane, "_EXECUTOR", None)
    assert asyncio.run(both()) == ["a", "b"]
    assert {name for _, name, _, _ in spans} == {"peer-import_0"}, spans
    first, second = sorted(spans, key=lambda s: s[2])
    assert first[3] <= second[2], spans
    import_lane._EXECUTOR.shutdown()
    monkeypatch.setattr(import_lane, "_EXECUTOR", None)
