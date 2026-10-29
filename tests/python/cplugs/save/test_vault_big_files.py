
from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import List

import pytest

from src.cplugs.save.scheduler import Follower
from src.core.blobcodec import chunking
from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault import health, restore, retention
from src.cplugs.save.vault.chunks import BlobStore
from src.cplugs.save.vault.follow import Engine, SliceResult
from src.cplugs.save.vault.store import STATUS_PARTIAL, STATUS_WRITTEN
from src.cplugs.sdk.blob_codec import Throttle
from tests.python.cplugs.save.vault_helpers import CONV, World, jsonl


@pytest.fixture(autouse=True)
def small_chunks(monkeypatch):
    monkeypatch.setattr(chunking, "CHUNK_TARGET_BYTES", 64 * 1024)


def _puts(monkeypatch) -> List[int]:
    count: List[int] = [0]
    real = BlobStore.put

    def counting(self, raw):
        count[0] += 1
        return real(self, raw)

    monkeypatch.setattr(BlobStore, "put", counting)
    return count


def _grow(world: World, lines: int, seed: int, bump: float) -> None:
    with open(world.transcript(), "ab") as handle:
        handle.write(jsonl(lines, seed=seed))
    os.utime(world.transcript(), (time.time() + bump, time.time() + bump))


def test_an_append_reads_only_the_tail_and_restores_byte_identical(tmp_path, monkeypatch):
    world = World(tmp_path)
    world.write_conversation(jsonl(4000), subagents=0, tool_results=0)
    world.capture()
    total = len(world.vault.manifests.newest(CONV).main().chunks)
    assert total >= 10
    count = _puts(monkeypatch)
    _grow(world, 20, seed=9, bump=5)
    assert world.capture().status == STATUS_WRITTEN
    assert count[0] <= 3
    newest = world.vault.manifests.newest(CONV)
    assert b"".join(restore.read_entry(world.vault.blobs, newest.main())) == world.transcript().read_bytes()
    assert newest.main().digests and len(newest.main().digests) == len(newest.main().chunks)
    restore.verify_manifest(world.vault.blobs, newest)


def test_an_append_whose_earlier_part_was_changed_in_place_is_read_whole(tmp_path, monkeypatch):
    world = World(tmp_path)
    world.write_conversation(jsonl(4000), subagents=0, tool_results=0)
    world.capture()
    body = bytearray(world.transcript().read_bytes())
    body[10:14] = b"ZZZZ"
    world.transcript().write_bytes(bytes(body) + jsonl(5, seed=2))
    os.utime(world.transcript(), (time.time() + 5, time.time() + 5))
    count = _puts(monkeypatch)
    assert world.capture().status == STATUS_WRITTEN
    assert count[0] >= 10
    newest = world.vault.manifests.newest(CONV)
    assert b"".join(restore.read_entry(world.vault.blobs, newest.main())) == world.transcript().read_bytes()
    assert world.vault.manifests.is_kept(CONV, world.vault.manifests.point_ids(CONV)[0])


def test_a_slice_that_runs_out_inside_a_file_resumes_and_publishes_only_the_finished_unit(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(4000), subagents=2, tool_results=2)
    throttle = Throttle(slice_seconds=0, sleep=lambda s: None)
    statuses = []
    for _ in range(200):
        throttle.begin_slice()
        outcome = world.capture(pace=throttle)
        statuses.append(outcome.status)
        if outcome.status != STATUS_PARTIAL:
            break
        assert world.vault.manifests.point_ids(CONV) == []
    assert statuses[-1] == STATUS_WRITTEN and statuses.count(STATUS_PARTIAL) >= 10
    assert not world.vault.partials
    newest = world.vault.manifests.newest(CONV)
    for entry in newest.files:
        assert b"".join(restore.read_entry(world.vault.blobs, entry)) == open(entry.source_path, "rb").read()


def test_the_resume_does_not_read_a_finished_file_again(tmp_path, monkeypatch):
    world = World(tmp_path)
    world.write_conversation(jsonl(1500), subagents=3, tool_results=3)
    count = _puts(monkeypatch)
    throttle = Throttle(slice_seconds=0, sleep=lambda s: None)
    for _ in range(300):
        throttle.begin_slice()
        if world.capture(pace=throttle).status != STATUS_PARTIAL:
            break
    assert world.vault.manifests.point_ids(CONV)
    stored = sum(len(f.chunks) for f in world.vault.manifests.newest(CONV).files)
    assert count[0] == stored


def test_the_engine_requeues_a_parked_unit_first_and_finishes_it_over_several_slices(tmp_path):
    world = World(tmp_path)
    ids = [f"{n:08d}-aaaa-bbbb-cccc-1234567890ab" for n in range(1, 4)]
    for conv in ids:
        world.write_conversation(jsonl(3000), conv=conv, subagents=0, tool_results=0)
    engine = Engine(lambda: world.vault, world.state, lambda: world.sources, throttle=Throttle(slice_seconds=0, sleep=lambda s: None))
    results = []
    for _ in range(400):
        results.append(engine.run_slice())
        if not results[-1].more:
            break
    assert sorted(world.vault.manifests.units()) == ids and len(results) > 6
    assert health.read(world.state)["uncovered"] == 0


def test_a_collection_does_not_wait_for_a_running_capture_and_a_capture_does_not_wait_for_a_collection_queue(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(50))
    world.capture()
    release = threading.Event()
    started = threading.Event()

    def long_capture() -> None:
        with world.vault.guard.capturing():
            started.set()
            release.wait(10)

    thread = threading.Thread(target=long_capture)
    thread.start()
    started.wait(5)
    began = time.monotonic()
    result = retention.collect_garbage(world.vault, grace=0)
    assert result.get("busy") == 1 and time.monotonic() - began < 1.0 and result["removed"] == 0
    other = "99999999-aaaa-bbbb-cccc-1234567890ab"
    world.write_conversation(jsonl(20), conv=other)
    began = time.monotonic()
    assert world.capture(other).status == STATUS_WRITTEN and time.monotonic() - began < 5.0
    release.set()
    thread.join()
    assert retention.collect_garbage(world.vault, grace=0).get("busy") is None


def test_a_capture_of_a_unit_does_not_wait_for_a_slow_capture_of_the_same_unit(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(2000), subagents=0, tool_results=0)
    gate = threading.Event()
    inside = threading.Event()

    class Slow:

        def rest(self, worked: float) -> None:
            if not gate.is_set():
                inside.set()
                gate.wait(30)

        def expired(self) -> bool:
            return False

    follower = threading.Thread(target=lambda: world.capture(reason="follow", pace=Slow()))
    follower.start()
    assert inside.wait(5)
    result = {}
    lifecycle = threading.Thread(target=lambda: result.update(outcome=world.capture(reason="kill")))
    lifecycle.start()
    lifecycle.join(15)
    waited = lifecycle.is_alive()
    gate.set()
    lifecycle.join(30)
    follower.join(30)
    assert not waited, "the lifecycle save of a conversation waited for the follower's read of the same conversation"
    assert result["outcome"].status in (STATUS_WRITTEN, "unchanged")
    newest = world.vault.manifests.newest(CONV)
    assert b"".join(restore.read_entry(world.vault.blobs, newest.main())) == world.transcript().read_bytes()


def test_cancel_ends_a_running_slice_at_its_next_chunk_and_wakes_a_rest():
    throttle = Throttle(duty=0.01, slice_seconds=1000)
    assert not throttle.expired()
    began = time.monotonic()
    timer = threading.Timer(0.2, throttle.cancel)
    timer.start()
    throttle.rest(2.0)
    assert time.monotonic() - began < 5 and throttle.cancelled and throttle.expired()


def test_stopping_the_follower_ends_the_running_slice_and_waits_for_the_thread():
    state = {"running": False, "ended": False}
    cancel = threading.Event()

    def slice_fn() -> SliceResult:
        state["running"] = True
        cancel.wait(30)
        state["ended"] = True
        return SliceResult()

    async def scenario() -> float:
        follower = Follower(slice_fn=slice_fn, period=0.01, retry=0.01, cancel=cancel.set)
        follower.start()
        while not state["running"]:
            await asyncio.sleep(0.01)
        began = time.monotonic()
        await follower.stop()
        return time.monotonic() - began

    took = asyncio.run(scenario())
    assert state["ended"] and took < 5


def test_coverage_is_judged_by_progress_not_by_the_age_of_the_first_backup(tmp_path):
    world = World(tmp_path)
    ids = [f"{n:08d}-aaaa-bbbb-cccc-1234567890ab" for n in range(1, 4)]
    for conv in ids:
        world.write_conversation(jsonl(3000), conv=conv, subagents=0, tool_results=0)
    clock = {"t": 1_000_000.0}
    engine = Engine(lambda: world.vault, world.state, lambda: world.sources, throttle=Throttle(slice_seconds=0, sleep=lambda s: None),
                    clock=lambda: clock["t"])
    seen = []
    for _ in range(400):
        clock["t"] += 3600
        result = engine.run_slice()
        record = health.read(world.state)
        seen.append((record["uncovered"], record["uncovered_since"]))
        if not result.more:
            break
    falling = [(count, since) for count, since in seen if count]
    assert falling[0][0] == 3 and falling[-1][0] <= 1
    assert falling[-1][1] > falling[0][1]
    assert health.read(world.state)["uncovered_since"] is None


def test_the_pause_between_busy_slices_is_short():
    assert K.BACKFILL_RETRY_SECONDS <= 5
