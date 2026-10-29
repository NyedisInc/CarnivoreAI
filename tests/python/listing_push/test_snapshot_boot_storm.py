
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict

from src.core.listing_push.publisher import Collection, CollectionResult, ListingPublisher

CLIENTS = 20
PASS_SECONDS = 0.3


class _SlowSource:

    def __init__(self) -> None:
        self.builds = 0
        self.slow = True
        self.version = 0

    async def build(self, context: Dict[str, Any]) -> CollectionResult:
        self.builds += 1
        if self.slow:
            await asyncio.sleep(PASS_SECONDS)
        return CollectionResult(rows=[{"id": "a", "v": self.version}])


def _publisher(source: _SlowSource, clients: int) -> ListingPublisher:
    return ListingPublisher([Collection("list", source.build, lambda r: r["id"])],
                            lambda frame: 0, lambda: clients, min_interval=0.0)


async def _storm(publisher: ListingPublisher) -> float:
    async def one() -> float:
        started = time.monotonic()
        await publisher.snapshot()
        return time.monotonic() - started
    return max(await asyncio.gather(*(one() for _ in range(CLIENTS))))


def test_storm_with_a_completed_pass_answers_at_once_and_builds_nothing() -> None:
    async def scenario() -> None:
        source = _SlowSource()
        publisher = _publisher(source, clients=1)
        await publisher.run_pass()
        source.version = 1
        publisher._computed_at -= 10.0
        seq = publisher.seq
        builds = source.builds
        running = asyncio.ensure_future(publisher.run_pass())
        await asyncio.sleep(0.05)
        worst = await _storm(publisher)
        print(f"wait: slowest of {CLIENTS} snapshots with a pass running: {worst * 1000:.1f} ms")
        assert worst < PASS_SECONDS / 3, "a snapshot waited behind the running pass"
        assert source.builds == builds + 1, "snapshots triggered extra builds"
        snap = await publisher.snapshot()
        assert snap["seq"] == seq and snap["stream"] == publisher.stream
        await running
        assert publisher.seq == seq + 1

    asyncio.run(scenario())


def test_storm_with_no_pass_yet_shares_exactly_one_build() -> None:
    async def scenario() -> None:
        source = _SlowSource()
        publisher = _publisher(source, clients=0)
        worst = await _storm(publisher)
        print(f"first paint: slowest of {CLIENTS} snapshots: {worst * 1000:.1f} ms")
        assert source.builds == 1, f"{source.builds} builds for {CLIENTS} cold snapshots"
        assert publisher.seq == 1

    asyncio.run(scenario())
