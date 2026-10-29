
from __future__ import annotations

import asyncio

import pytest

from src.core.notifications.contracts import FailureClass as F
from tests.python.notifications.engine_fakes import OK, FakeSender, dest, ev, fail
from tests.python.notifications.test_engine import Rig

pytestmark = pytest.mark.asyncio

SLACK, DISCORD = "d_000000000001", "d_000000000002"


def two_destinations(slack_sender, discord_sender) -> Rig:
    rig = Rig([dest(1, kind="slack"), dest(2, kind="discord")])
    senders = {"slack": slack_sender, "discord": discord_sender}
    rig.engine._sender_lookup = lambda kind: senders[kind]
    return rig


async def test_a_raising_sender_does_not_stop_a_healthy_destination() -> None:
    class Boom:
        async def send(self, event, config, secrets):
            raise RuntimeError("sender bug")

    healthy = FakeSender()
    rig = two_destinations(Boom(), healthy)
    await rig.send(ev())
    assert len(healthy.calls) == 1
    assert rig.engine.statuses()[DISCORD].last_ok_ts is not None
    assert rig.engine.statuses()[SLACK].last_failure == "network"


async def test_a_failure_is_reported_by_destination_and_never_resent_to_the_one_that_succeeded() -> None:
    ok_sender = FakeSender()
    failing = FakeSender(fail(F.SERVER), fail(F.SERVER), fail(F.SERVER))
    rig = two_destinations(failing, ok_sender)
    await rig.send(ev())
    assert len(failing.calls) == 3 and len(ok_sender.calls) == 1
    assert rig.engine.statuses()[SLACK].last_failure == "server"
    assert rig.engine.statuses()[DISCORD].last_failure is None


async def test_a_slow_destination_does_not_hold_the_fast_one() -> None:
    gate = asyncio.Event()

    class Slow:
        calls = 0

        async def send(self, event, config, secrets):
            Slow.calls += 1
            await gate.wait()
            return OK

    fast = FakeSender()
    rig = two_destinations(Slow(), fast)
    await rig.engine.handle(ev())
    for _ in range(10):
        await asyncio.sleep(0)
    assert len(fast.calls) == 1 and Slow.calls == 1
    gate.set()
    await rig.engine.join()


async def test_one_destinations_sends_keep_their_order() -> None:
    sender = FakeSender()
    rig = Rig([dest()], sender=sender)
    events = [ev(instance_key=f"e{i}", session_id=f"s{i}") for i in range(6)]
    await rig.send(*events)
    assert [c[0].instance_key for c in sender.calls] == [e.instance_key for e in events]


async def test_stopping_the_engine_mid_delivery_ends_every_worker() -> None:
    gate = asyncio.Event()

    class Hang:
        async def send(self, event, config, secrets):
            await gate.wait()
            return OK

    rig = Rig([dest()], sender=Hang())
    await rig.engine.handle(ev())
    for _ in range(5):
        await asyncio.sleep(0)
    lanes = list(rig.engine._lanes.values())
    assert lanes and lanes[0]._task is not None and not lanes[0]._task.done()
    await rig.engine.stop()
    assert all(lane._task.done() for lane in lanes)
