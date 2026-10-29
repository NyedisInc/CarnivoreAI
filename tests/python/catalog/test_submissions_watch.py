
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import pytest
from fastapi import HTTPException

from src.core.catalog.submissions_watch import (
    BACKOFF_SECONDS, FAST_SECONDS, MIN_FORCE_GAP_SECONDS, SLOW_SECONDS, STALE_AFTER_SECONDS, SubmissionsWatch,
)
from src.core.resource_push import topics
from tests.helpers import hosted_catalog_fake as fake
from tests.helpers import submissions_harness as h


@pytest.fixture(scope="module")
def api():
    with fake.lambda_modules(h.JWT_TEST_SECRET) as namespace:
        yield namespace


def row(api: Any, sid: str, status: str = "pending", gate_state: str = "gating", events: int = 0) -> Dict[str, Any]:
    built = api.submissions.mine_row({"submission_id": sid, "status": status, "gate_state": gate_state, "name": sid[:3]})
    if events:
        built["events"] = [{"at": "t", "what": "x"}] * events
    return built


class Clock:

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Hosted:

    def __init__(self, rows: List[Dict[str, Any]]) -> None:
        self.rows = rows
        self.calls = 0
        self.error: Optional[HTTPException] = None

    async def __call__(self) -> Dict[str, Any]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return {"submissions": list(self.rows)}


async def idle_forever(_: float) -> None:
    await asyncio.Event().wait()


def make(clock: Clock, sleep: Any = idle_forever) -> "tuple[SubmissionsWatch, List[str]]":
    named: List[str] = []
    return SubmissionsWatch(clock=clock, notify=named.append, sleep=sleep), named


def test_topic_is_declared_and_advertised() -> None:
    assert topics.CATALOG_SUBMISSIONS == "catalog_submissions"
    assert topics.CATALOG_SUBMISSIONS in topics.RESOURCE_TOPICS


def test_next_delay_follows_the_open_rows(api) -> None:
    async def scenario() -> List[Optional[float]]:
        out: List[Optional[float]] = []
        for rows in (
            [row(api, "a" * 32, gate_state="gating")],
            [row(api, "b" * 32, gate_state="received")],
            [row(api, "c" * 32, gate_state="awaiting_approval")],
            [row(api, "d" * 32, gate_state="stuck")],
            [row(api, "e" * 32, status="approved", gate_state="awaiting_approval")],
            [row(api, "f" * 32, status="publishing", gate_state="")],
            [row(api, "1" * 32, status="rejected", gate_state="")],
            [row(api, "2" * 32, status="withdrawn", gate_state=""), row(api, "3" * 32, gate_state="gating")],
            [],
        ):
            watch, _ = make(Clock())
            await watch.poll_once(Hosted(rows))
            out.append(watch.next_delay())
        return out

    assert asyncio.run(scenario()) == [
        FAST_SECONDS, FAST_SECONDS, SLOW_SECONDS, SLOW_SECONDS, SLOW_SECONDS, SLOW_SECONDS, None, FAST_SECONDS, None,
    ]


def test_a_429_backs_off_fifteen_minutes(api) -> None:
    async def scenario() -> Optional[float]:
        watch, _ = make(Clock())
        hosted = Hosted([row(api, "a" * 32)])
        await watch.poll_once(hosted)
        hosted.error = HTTPException(status_code=429, detail={"code": "rate_limited"})
        await watch.poll_once(hosted)
        return watch.next_delay()

    assert asyncio.run(scenario()) == BACKOFF_SECONDS


def test_identical_reads_notify_once_and_a_change_notifies(api) -> None:
    async def scenario() -> List[List[str]]:
        watch, named = make(Clock())
        hosted = Hosted([row(api, "a" * 32, gate_state="gating")])
        seen: List[List[str]] = []
        await watch.poll_once(hosted)
        await watch.poll_once(hosted)
        seen.append(list(named))
        hosted.rows = [row(api, "a" * 32, gate_state="awaiting_approval")]
        await watch.poll_once(hosted)
        seen.append(list(named))
        hosted.rows = [row(api, "a" * 32, gate_state="awaiting_approval", events=2)]
        await watch.poll_once(hosted)
        seen.append(list(named))
        hosted.rows = [row(api, "a" * 32, status="approved", gate_state="awaiting_approval", events=2)]
        await watch.poll_once(hosted)
        seen.append(list(named))
        return seen

    seen = asyncio.run(scenario())
    topic = topics.CATALOG_SUBMISSIONS
    assert seen == [[topic], [topic] * 2, [topic] * 3, [topic] * 4]


def test_the_route_serves_the_cache_and_refreshes_once_when_stale(api) -> None:
    async def scenario() -> List[int]:
        clock = Clock()
        watch, _ = make(clock)
        hosted = Hosted([row(api, "a" * 32, gate_state="awaiting_approval")])
        calls: List[int] = []
        await watch.mine(hosted)
        calls.append(hosted.calls)
        for _ in range(5):
            await watch.mine(hosted)
        calls.append(hosted.calls)
        clock.now += STALE_AFTER_SECONDS + 1
        await watch.mine(hosted)
        await watch.mine(hosted)
        await watch.drain()
        calls.append(hosted.calls)
        return calls

    assert asyncio.run(scenario()) == [1, 1, 2]


def test_a_forced_refresh_inside_ten_seconds_does_not_read(api) -> None:
    async def scenario() -> List[int]:
        clock = Clock()
        watch, _ = make(clock)
        hosted = Hosted([row(api, "a" * 32)])
        await watch.mine(hosted)
        clock.now += MIN_FORCE_GAP_SECONDS - 1
        await watch.mine(hosted, force=True)
        inside = hosted.calls
        clock.now += 2
        await watch.mine(hosted, force=True)
        await watch.drain()
        return [inside, hosted.calls]

    assert asyncio.run(scenario()) == [1, 2]


def test_signed_out_never_reads_again_and_drops_the_cache(api) -> None:
    async def scenario() -> Any:
        clock = Clock()
        watch, _ = make(clock)
        hosted = Hosted([row(api, "a" * 32)])
        await watch.mine(hosted)
        clock.now += MIN_FORCE_GAP_SECONDS + 1
        hosted.error = HTTPException(status_code=403, detail={"code": "signed_out"})
        with pytest.raises(HTTPException):
            await watch.mine(hosted, force=True)
        assert watch.next_delay() is None
        calls = hosted.calls
        watch.after_write(hosted)
        await watch.drain()
        return calls, hosted.calls

    first, after = asyncio.run(scenario())
    assert after == first + 1, "after_write may try once; the 403 ends it and nothing polls"


def test_after_write_reads_once_and_notifies(api) -> None:
    async def scenario() -> List[str]:
        watch, named = make(Clock())
        hosted = Hosted([row(api, "a" * 32, gate_state="gating")])
        await watch.mine(hosted)
        hosted.rows = [row(api, "a" * 32, gate_state="gating"), row(api, "b" * 32, gate_state="received")]
        watch.after_write(hosted)
        await watch.drain()
        return named

    assert asyncio.run(scenario()) == [topics.CATALOG_SUBMISSIONS] * 2


def test_the_poller_runs_while_a_row_is_open_and_stops_itself(api) -> None:
    async def scenario() -> Any:
        clock = Clock()
        async def one_tick(_: float) -> None:
            await asyncio.sleep(0)

        watch, _ = make(clock, one_tick)
        hosted = Hosted([row(api, "a" * 32, gate_state="gating")])
        await watch.mine(hosted)
        assert watch.running
        hosted.rows = [row(api, "a" * 32, status="rejected", gate_state="")]
        await watch.poller
        return watch.running, watch.next_delay(), hosted.calls

    running, delay, calls = asyncio.run(scenario())
    assert (running, delay) == (False, None) and calls >= 2


def test_a_sign_in_change_drops_the_cache_and_discards_a_read_in_flight(api) -> None:
    async def scenario() -> Any:
        watch, named = make(Clock())
        hosted = Hosted([row(api, "a" * 32, gate_state="awaiting_approval")])
        await watch.mine(hosted)
        watch.session_changed({"signed_in": False})
        dropped = watch.next_delay()
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow() -> Dict[str, Any]:
            started.set()
            await release.wait()
            return {"submissions": [row(api, "b" * 32)]}

        pending = asyncio.ensure_future(watch.mine(slow))
        await started.wait()
        watch.session_changed({"signed_in": True})
        release.set()
        await pending
        return dropped, watch.next_delay(), named.count(topics.CATALOG_SUBMISSIONS)

    dropped, after, told = asyncio.run(scenario())
    assert dropped is None and after is None, "the old account's rows must not outlive the sign out"
    assert told == 3
