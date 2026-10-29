
from __future__ import annotations

import os
import threading
import time

from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault import follow, health, legacy, retention
from src.cplugs.save.vault.follow import Engine
from src.cplugs.sdk.blob_codec import Throttle
from tests.python.cplugs.save.vault_helpers import World, jsonl


def test_a_failed_old_point_is_counted_in_health_and_retried_later_not_forgotten(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(20))
    calls = []
    clock = {"t": 1_000_000.0}

    def migrate(vault, throttle):
        calls.append(clock["t"])
        return legacy.LegacyProgress(more=False, failed=2 if len(calls) == 1 else 0)

    engine = Engine(lambda: world.vault, world.state, lambda: world.sources, legacy=migrate,
                    throttle=Throttle(sleep=lambda s: None), clock=lambda: clock["t"])
    while engine.run_slice().more:
        pass
    assert len(calls) == 1 and health.read(world.state)["legacy_unmigrated"] == 2
    assert health.evaluate(health.read(world.state))["legacy_unmigrated"] == 2
    assert engine.run_slice().more is False and len(calls) == 1
    clock["t"] += K.LEGACY_RETRY_SECONDS + 1
    engine.run_slice()
    assert len(calls) == 2 and health.read(world.state)["legacy_unmigrated"] == 0
    clock["t"] += K.LEGACY_RETRY_SECONDS * 3
    engine.run_slice()
    assert len(calls) == 2


def test_a_collection_that_finds_a_capture_running_comes_back_in_a_minute_not_a_day(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(20))
    clock = {"t": 1_000_000.0}
    engine = Engine(lambda: world.vault, world.state, lambda: world.sources, throttle=Throttle(sleep=lambda s: None),
                    clock=lambda: clock["t"])
    held, release = threading.Event(), threading.Event()

    def hold() -> None:
        with world.vault.guard.capturing():
            held.set()
            release.wait(10)

    thread = threading.Thread(target=hold)
    thread.start()
    held.wait(5)
    try:
        while engine.run_slice().more:
            pass
        assert engine._gc_at == clock["t"] - follow.GC_SECONDS + follow.GC_BUSY_RETRY_SECONDS
    finally:
        release.set()
        thread.join()
    clock["t"] += follow.GC_BUSY_RETRY_SECONDS + 1
    engine.run_slice()
    assert engine._gc_at == clock["t"]


def test_raising_the_cap_clears_over_cap_at_the_next_assessment_without_a_write(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(300))
    world.capture()
    world.side_history(3)
    cap = {"bytes": 1}
    clock = {"t": 1_000_000.0}
    engine = Engine(lambda: world.vault, world.state, lambda: world.sources, cap_bytes=lambda: cap["bytes"],
                    throttle=Throttle(sleep=lambda s: None), clock=lambda: clock["t"])
    while engine.run_slice().more:
        pass
    assert retention.read_state(world.vault.root)["over_cap"] is True
    cap["bytes"] = 10 * 1024 ** 3
    clock["t"] += follow.ASSESS_SECONDS + 1
    engine.run_slice()
    assert retention.read_state(world.vault.root)["over_cap"] is False and health.read(world.state)["over_cap"] is False
