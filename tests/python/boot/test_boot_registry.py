
from __future__ import annotations

import asyncio

import pytest
from structlog.testing import capture_logs

from src.core.boot.context import BootContext
from src.core.boot.steps import BootRegistry, BootRegistryError, BootRunner, BootStep, FailureMode


def _recording_step(name: str, order: int, journal: list[str], **kwargs: object) -> BootStep:

    async def start(_ctx: BootContext) -> None:
        journal.append(f"start:{name}")

    def stop(_ctx: BootContext) -> None:
        journal.append(f"stop:{name}")

    fields: dict[str, object] = {"start": start, "stop": stop}
    fields.update(kwargs)
    return BootStep(name=name, order=order, **fields)  # type: ignore[arg-type]


def _ctx() -> BootContext:
    return BootContext(app=None)  # type: ignore[arg-type]


def _boom(_ctx: BootContext) -> None:
    raise OSError("disk said no")


def test_steps_start_in_order_and_stop_in_reverse() -> None:
    journal: list[str] = []
    registry = BootRegistry()
    for name, order in (("c", 30), ("a", 10), ("b", 20)):
        registry.register(_recording_step(name, order, journal))
    runner = BootRunner(registry)

    async def go() -> None:
        await runner.start_all(_ctx())
        await runner.stop_all(_ctx())

    asyncio.run(go())
    assert journal == ["start:a", "start:b", "start:c", "stop:c", "stop:b", "stop:a"]


def test_stop_order_moves_one_step_without_moving_its_start() -> None:
    journal: list[str] = []
    registry = BootRegistry([
        _recording_step("a", 10, journal),
        _recording_step("b", 20, journal, stop_order=5),
    ])
    runner = BootRunner(registry)

    async def go() -> None:
        await runner.start_all(_ctx())
        await runner.stop_all(_ctx())

    asyncio.run(go())
    assert journal == ["start:a", "start:b", "stop:a", "stop:b"]


def test_a_fatal_step_aborts_the_boot_and_rolls_back_what_started() -> None:
    journal: list[str] = []
    registry = BootRegistry([
        _recording_step("first", 10, journal),
        BootStep(name="broken", order=20, start=_boom, stop=lambda _c: journal.append("stop:broken")),
        _recording_step("never", 30, journal),
    ])
    runner = BootRunner(registry)
    with pytest.raises(OSError, match="disk said no"):
        asyncio.run(runner.start_all(_ctx()))
    assert journal == ["start:first", "stop:first"]


def test_a_degraded_step_logs_its_event_and_the_boot_continues() -> None:
    journal: list[str] = []
    registry = BootRegistry([
        BootStep(name="flaky", order=10, start=_boom, stop=lambda _c: journal.append("stop:flaky"),
                 failure=FailureMode.DEGRADED, degrades_on=(OSError,), failure_event="flaky_start_failed"),
        _recording_step("after", 20, journal),
    ])
    runner = BootRunner(registry)

    async def go() -> None:
        await runner.start_all(_ctx())
        await runner.stop_all(_ctx())

    with capture_logs() as logs:
        asyncio.run(go())
    assert journal == ["start:after", "stop:after"]
    failed = [entry for entry in logs if entry["event"] == "flaky_start_failed"]
    assert failed and failed[0]["error"] == "disk said no" and failed[0]["log_level"] == "warning"


def test_a_degraded_step_still_aborts_on_an_error_it_did_not_name() -> None:
    def wrong_kind(_ctx: BootContext) -> None:
        raise RuntimeError("not an OSError")

    registry = BootRegistry([BootStep(name="narrow", order=10, start=wrong_kind, failure=FailureMode.DEGRADED,
                                      degrades_on=(OSError,), failure_event="narrow_failed")])
    with pytest.raises(RuntimeError):
        asyncio.run(BootRunner(registry).start_all(_ctx()))


def test_a_blanket_swallow_must_say_why() -> None:
    with pytest.raises(BootRegistryError):
        BootStep(name="silent", order=10, start=_boom, failure=FailureMode.DEGRADED,
                 degrades_on=(Exception,), failure_event="silent_failed")


def test_duplicate_names_and_orders_are_refused() -> None:
    registry = BootRegistry([BootStep(name="a", order=10)])
    with pytest.raises(BootRegistryError):
        registry.register(BootStep(name="a", order=20))
    with pytest.raises(BootRegistryError):
        registry.register(BootStep(name="b", order=10))


def test_a_failing_stop_is_logged_and_the_later_stops_still_run() -> None:
    journal: list[str] = []

    def broken_stop(_ctx: BootContext) -> None:
        raise RuntimeError("stop said no")

    registry = BootRegistry([
        _recording_step("first", 10, journal),
        BootStep(name="broken", order=20, stop=broken_stop),
        _recording_step("last", 30, journal),
    ])
    runner = BootRunner(registry)

    async def go() -> None:
        await runner.start_all(_ctx())
        await runner.stop_all(_ctx())

    with capture_logs() as logs:
        asyncio.run(go())
    assert journal == ["start:first", "start:last", "stop:last", "stop:first"]
    failed = [(e["step"], e["error_type"]) for e in logs if e["event"] == "lifespan_teardown_step_failed"]
    assert failed == [("broken", "RuntimeError")]


def test_a_stop_that_requires_a_failed_stop_is_skipped() -> None:
    journal: list[str] = []

    def broken_stop(_ctx: BootContext) -> None:
        raise RuntimeError("relay said no")

    registry = BootRegistry([
        _recording_step("store", 10, journal, stop_requires=("relay",)),
        BootStep(name="relay", order=20, stop=broken_stop),
    ])
    runner = BootRunner(registry)

    async def go() -> None:
        await runner.start_all(_ctx())
        await runner.stop_all(_ctx())

    with capture_logs() as logs:
        asyncio.run(go())
    assert journal == ["start:store"]
    assert [e["step"] for e in logs if e["event"] == "lifespan_teardown_step_skipped"] == ["store"]


def test_a_required_teardown_name_that_no_step_has_is_refused() -> None:
    with pytest.raises(BootRegistryError, match="unknown teardown name"):
        BootRegistry([BootStep(name="store", order=10, stop=lambda _c: None, stop_requires=("relya",))])


def test_a_required_teardown_name_torn_down_after_the_requiring_step_is_refused() -> None:
    with pytest.raises(BootRegistryError, match="torn down after it"):
        BootRegistry([
            BootStep(name="store", order=20, stop=lambda _c: None, stop_requires=("relay",)),
            BootStep(name="relay", order=10, stop=lambda _c: None),
        ])


def test_register_refuses_a_bad_requirement_and_keeps_the_registry_unchanged() -> None:
    registry = BootRegistry([BootStep(name="a", order=10, stop=lambda _c: None)])
    with pytest.raises(BootRegistryError):
        registry.register(BootStep(name="b", order=5, stop=lambda _c: None, stop_requires=("nope",)))
    assert [s.name for s in registry.start_sequence()] == ["a"]


def test_a_part_the_step_did_not_declare_is_refused_and_logged() -> None:
    async def stop(ctx: BootContext) -> None:
        await ctx.stop_part("declared", lambda: None)
        await ctx.stop_part("undeclared", lambda: None)

    runner = BootRunner(BootRegistry([BootStep(name="multi", order=10, stop=stop, stop_parts=("declared",))]))

    async def go() -> None:
        await runner.start_all(_ctx())
        await runner.stop_all(_ctx())

    with capture_logs() as logs:
        asyncio.run(go())
    assert [(e["step"], e["error_type"]) for e in logs if e["event"] == "lifespan_teardown_step_failed"] == [
        ("multi", "BootContextError")]


def test_a_fatal_failure_after_a_boot_stops_each_earlier_step_once_and_never_the_failed_one() -> None:
    stops: dict[str, int] = {}

    def counting_step(name: str, order: int, start: object = None) -> BootStep:
        return BootStep(name=name, order=order, start=start or (lambda _c: None),  # type: ignore[arg-type]
                        stop=lambda _c: stops.__setitem__(name, stops.get(name, 0) + 1))

    runner = BootRunner(BootRegistry([
        counting_step("config", 10), counting_step("services", 20), counting_step("fatal", 30, _boom),
        counting_step("after", 40),
    ]))
    ctx = _ctx()
    with pytest.raises(OSError):
        asyncio.run(runner.start_all(ctx))
    asyncio.run(runner.stop_all(ctx))
    assert stops == {"services": 1, "config": 1}
    assert list(stops) == ["services", "config"]
