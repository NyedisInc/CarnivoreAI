from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_sf_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_sf_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.single_flight import (  # noqa: E402
    SESSION_LIST_FLIGHT_ATTR,
    SESSION_LIST_FLIGHT_NAME,
    SingleFlight,
    flight_on,
)

CALLERS = 5

MAX_TURNS = 100


class _Pass:

    def __init__(self) -> None:
        self.runs = 0
        self.gate = asyncio.Event()
        self.fail_with: BaseException | None = None

    async def __call__(self) -> list:
        self.runs += 1
        mine = self.runs
        await self.gate.wait()
        if self.fail_with is not None:
            raise self.fail_with
        return ["pass", mine]


async def _settle(turns: int = MAX_TURNS) -> None:
    for _ in range(turns):
        await asyncio.sleep(0)



def test_concurrent_callers_share_one_pass():

    async def scenario():
        work = _Pass()
        flight: SingleFlight[Any] = SingleFlight("test")
        callers = [
            asyncio.create_task(flight.run(work)) for _ in range(CALLERS)
        ]
        await _settle()
        assert work.runs == 1, (
            f"{work.runs} passes started while only one was needed"
        )
        work.gate.set()
        results = await asyncio.gather(*callers)
        return work, flight, results

    work, flight, results = asyncio.run(scenario())
    assert work.runs == 1, f"{CALLERS} callers cost {work.runs} passes"
    assert all(r == ["pass", 1] for r in results), results
    assert flight.passes_started == 1
    assert flight.callers_served == CALLERS
    assert flight.callers_coalesced == CALLERS - 1
    assert not flight.in_flight


def test_the_harness_detects_an_implementation_that_does_not_coalesce():

    class _NoCoalescing:
        async def run(self, work: Callable[[], Awaitable[Any]]) -> Any:
            return await work()

    async def scenario():
        work = _Pass()
        flight = _NoCoalescing()
        callers = [
            asyncio.create_task(flight.run(work)) for _ in range(CALLERS)
        ]
        await _settle()
        runs_during = work.runs
        work.gate.set()
        await asyncio.gather(*callers)
        return runs_during

    assert asyncio.run(scenario()) == CALLERS, (
        "the harness did not see redundant passes, so the coalescing test "
        "above is worthless"
    )



def test_a_caller_arriving_after_a_pass_gets_a_fresh_one():

    async def scenario():
        work = _Pass()
        work.gate.set()
        flight: SingleFlight[Any] = SingleFlight("test")
        first = await flight.run(work)
        second = await flight.run(work)
        return work, flight, first, second

    work, flight, first, second = asyncio.run(scenario())
    assert work.runs == 2, "the second caller was served a remembered answer"
    assert first == ["pass", 1]
    assert second == ["pass", 2]
    assert flight.passes_started == 2
    assert flight.callers_coalesced == 0
    assert not flight.in_flight


def test_a_finished_flight_is_never_joined_even_before_it_is_retired():
    from src.core.single_flight import _Flight

    async def scenario():
        work = _Pass()
        work.gate.set()
        flight: SingleFlight[Any] = SingleFlight("test")
        stale = asyncio.ensure_future(work())
        await stale
        flight._flight = _Flight(task=stale)
        fresh = await flight.run(work)
        return work.runs, fresh

    runs, fresh = asyncio.run(scenario())
    assert runs == 2, "a finished flight was joined instead of replaced"
    assert fresh == ["pass", 2]


def test_the_harness_detects_a_cache():

    class _Caching:
        def __init__(self) -> None:
            self.task: asyncio.Task | None = None

        async def run(self, work: Callable[[], Awaitable[Any]]) -> Any:
            if self.task is None:
                self.task = asyncio.ensure_future(work())
            return await asyncio.shield(self.task)

    async def scenario():
        work = _Pass()
        work.gate.set()
        flight = _Caching()
        first = await flight.run(work)
        second = await flight.run(work)
        return work.runs, first, second

    runs, first, second = asyncio.run(scenario())
    assert runs == 1 and first == second, (
        "the harness could not tell a remembered answer from a fresh one, so "
        "the freshness test above is worthless"
    )



def test_a_failure_reaches_every_awaiter_and_clears_the_flight():

    async def scenario():
        work = _Pass()
        work.fail_with = ValueError("the pass failed")
        flight: SingleFlight[Any] = SingleFlight("test")
        callers = [
            asyncio.create_task(flight.run(work)) for _ in range(CALLERS)
        ]
        await _settle()
        work.gate.set()
        raised = await asyncio.gather(*callers, return_exceptions=True)
        work.fail_with = None
        after = await flight.run(work)
        return work, flight, raised, after

    work, flight, raised, after = asyncio.run(scenario())
    assert len(raised) == CALLERS
    assert all(isinstance(r, ValueError) for r in raised), raised
    assert all(str(r) == "the pass failed" for r in raised)
    assert work.runs == 2, "the failed pass was re-used instead of re-run"
    assert after == ["pass", 2]
    assert not flight.in_flight


def test_the_harness_detects_a_poisoned_flight():

    class _Poisoned:
        def __init__(self) -> None:
            self.task: asyncio.Task | None = None

        async def run(self, work: Callable[[], Awaitable[Any]]) -> Any:
            if self.task is None:
                self.task = asyncio.ensure_future(work())
            return await asyncio.shield(self.task)

    async def scenario():
        work = _Pass()
        work.fail_with = ValueError("the pass failed")
        work.gate.set()
        flight = _Poisoned()
        with pytest.raises(ValueError):
            await flight.run(work)
        work.fail_with = None
        with pytest.raises(ValueError):
            await flight.run(work)
        return work.runs

    assert asyncio.run(scenario()) == 1, (
        "the harness did not notice a retained failure, so the failure test "
        "above is worthless"
    )



def test_cancelling_the_starter_still_delivers_to_the_others():

    async def scenario():
        work = _Pass()
        flight: SingleFlight[Any] = SingleFlight("test")
        starter = asyncio.create_task(flight.run(work))
        await _settle()
        others = [
            asyncio.create_task(flight.run(work))
            for _ in range(CALLERS - 1)
        ]
        await _settle()
        assert work.runs == 1
        starter.cancel()
        await _settle()
        work.gate.set()
        results = await asyncio.gather(*others)
        return work, starter, results

    work, starter, results = asyncio.run(scenario())
    assert starter.cancelled(), "the starter was supposed to be cancelled"
    assert work.runs == 1
    assert all(r == ["pass", 1] for r in results), results


def test_the_harness_detects_an_unshielded_await():

    class _Unshielded:
        def __init__(self) -> None:
            self.task: asyncio.Task | None = None

        async def run(self, work: Callable[[], Awaitable[Any]]) -> Any:
            if self.task is None or self.task.done():
                self.task = asyncio.ensure_future(work())
            return await self.task

    async def scenario():
        work = _Pass()
        flight = _Unshielded()
        starter = asyncio.create_task(flight.run(work))
        await _settle()
        others = [
            asyncio.create_task(flight.run(work))
            for _ in range(CALLERS - 1)
        ]
        await _settle()
        starter.cancel()
        await _settle()
        work.gate.set()
        return await asyncio.gather(*others, return_exceptions=True)

    outcomes = asyncio.run(scenario())
    assert any(isinstance(o, asyncio.CancelledError) for o in outcomes), (
        "cancelling one caller did not disturb the others even without a "
        "shield, so the cancellation test above is worthless"
    )


def test_every_caller_cancelling_leaves_nothing_behind():

    async def scenario():
        work = _Pass()
        flight: SingleFlight[Any] = SingleFlight("test")
        callers = [
            asyncio.create_task(flight.run(work)) for _ in range(CALLERS)
        ]
        await _settle()
        for caller in callers:
            caller.cancel()
        await _settle()
        work.gate.set()
        await _settle()
        outcomes = await asyncio.gather(*callers, return_exceptions=True)
        fresh = await flight.run(work)
        return work, flight, outcomes, fresh

    work, flight, outcomes, fresh = asyncio.run(scenario())
    assert all(isinstance(o, asyncio.CancelledError) for o in outcomes)
    assert work.runs == 2
    assert fresh == ["pass", 2]
    assert not flight.in_flight



def test_the_sessions_list_endpoint_coalesces():
    from src.api import session_crud_routes as routes

    class _FakeState:
        pass

    class _FakeApp:
        def __init__(self, manager: Any) -> None:
            self.state = _FakeState()
            self.state.session_manager = manager

    class _FakeRequest:
        def __init__(self, manager: Any) -> None:
            self.app = _FakeApp(manager)
            self.state = _FakeState()

    class _FakeManager:
        def __init__(self, work: _Pass) -> None:
            self._work = work

        async def list_session_infos(self) -> list:
            await self._work()
            return []

    async def scenario():
        work = _Pass()
        manager = _FakeManager(work)
        request = _FakeRequest(manager)
        callers = [
            asyncio.create_task(routes.list_sessions(request))
            for _ in range(CALLERS)
        ]
        await _settle()
        during = work.runs
        work.gate.set()
        results = await asyncio.gather(*callers)
        parked = getattr(manager, SESSION_LIST_FLIGHT_ATTR, None)
        return during, work.runs, results, parked

    during, runs, results, parked = asyncio.run(scenario())
    assert during == 1, f"the endpoint started {during} concurrent passes"
    assert runs == 1
    assert all(r == [] for r in results)
    assert isinstance(parked, SingleFlight)


def test_flight_on_returns_the_same_instance_per_owner():

    class _Owner:
        pass

    first_owner = _Owner()
    second_owner = _Owner()
    a = flight_on(first_owner, SESSION_LIST_FLIGHT_ATTR, SESSION_LIST_FLIGHT_NAME)
    b = flight_on(first_owner, SESSION_LIST_FLIGHT_ATTR, SESSION_LIST_FLIGHT_NAME)
    c = flight_on(second_owner, SESSION_LIST_FLIGHT_ATTR, SESSION_LIST_FLIGHT_NAME)
    assert a is b
    assert a is not c
