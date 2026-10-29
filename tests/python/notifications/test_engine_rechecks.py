
from __future__ import annotations

import pytest

from src.core.notifications.contracts import FailureClass as F
from src.core.notifications.sms_cap import SmsDayCount
from tests.python.notifications.engine_fakes import FakeSender, dest, ev, fail
from tests.python.notifications.test_engine import Rig, _backlogged, _clean  # noqa: F401

pytestmark = pytest.mark.asyncio

D1 = "d_000000000001"


async def _release(r: Rig) -> None:
    await r.sleep.release()
    await r.engine.join()


async def test_item_queued_before_the_destination_was_disabled_is_not_sent() -> None:
    r = Rig([dest()], manual=True)
    await _backlogged(r)
    r.view.dests = [dest(enabled=False)]
    await _release(r)
    assert len(r.sender.calls) == 20


async def test_item_queued_before_the_destination_was_removed_is_not_sent() -> None:
    r = Rig([dest()], manual=True)
    await _backlogged(r)
    r.view.dests = []
    await _release(r)
    assert len(r.sender.calls) == 20


async def test_item_queued_before_the_type_was_unticked_is_not_sent() -> None:
    r = Rig([dest()], manual=True)
    await _backlogged(r)
    r.view.ticks[(D1, "session.finished")] = False
    await _release(r)
    assert len(r.sender.calls) == 20


async def test_a_queued_item_goes_out_with_the_current_config_not_the_enqueued_one() -> None:
    r = Rig([dest(config={"channel": "old"})], manual=True)
    await _backlogged(r)
    r.view.dests = [dest(config={"channel": "new"})]
    await _release(r)
    assert len(r.sender.calls) == 21
    assert r.sender.calls[0][1]["channel"] == "old" and r.sender.calls[-1][1]["channel"] == "new"


async def test_details_turned_off_after_the_enqueue_are_not_sent() -> None:
    r = Rig([dest(details=True)], manual=True)
    events = [ev(instance_key=f"q{i}", session_id=f"s{i}", details="private words") for i in range(21)]
    for e in events:
        await r.engine.handle(e)
    for _ in range(20):
        import asyncio
        await asyncio.sleep(0)
    r.view.dests = [dest(details=False)]
    await _release(r)
    assert len(r.sender.calls) == 21
    assert r.sender.calls[-1][0].details is None and r.sender.calls[-1][1]["details"] is False


async def test_a_retry_goes_out_with_the_current_config() -> None:
    class EditsOnFirstSend(FakeSender):
        async def send(self, event, config, secrets):
            r.view.dests = [dest(config={"channel": "edited"})]
            return await super().send(event, config, secrets)

    r = Rig([dest(config={"channel": "old"})], sender=EditsOnFirstSend(fail(F.TIMEOUT)))
    await r.send(ev())
    assert [c[1]["channel"] for c in r.sender.calls] == ["old", "edited"]


async def test_the_mute_stored_on_the_session_row_covers_an_auto_slept_session_gone_from_the_registry() -> None:
    r = Rig([dest()], uuid_muted={"u-slept"})
    await r.send(ev("session.auto_slept", session_id="ses_gone", session_uuid="u-slept"))
    assert r.sender.calls == []
    await r.send(ev("session.auto_slept", session_id="ses_gone2", session_uuid="u-other"))
    assert len(r.sender.calls) == 1


async def test_sms_retries_count_toward_the_day_cap() -> None:
    r = Rig([dest(kind="twilio")], sender=FakeSender(*[fail(F.TIMEOUT)] * 60))
    r.secret = {"numbers": "+15550000001"}
    await r.send(*[ev(instance_key=f"e{i}", session_id=f"s{i}") for i in range(10)])
    assert len(r.sender.calls) == 20


async def test_sms_day_count_survives_a_restart(tmp_path) -> None:
    r = Rig([dest(kind="twilio")], sms_state_dir=tmp_path)
    r.secret = {"numbers": "+15550000001"}
    await r.send(*[ev(instance_key=f"e{i}", session_id=f"s{i}") for i in range(15)])
    assert len(r.sender.calls) == 15
    again = Rig([dest(kind="twilio")], sms_state_dir=tmp_path)
    again.secret = {"numbers": "+15550000001"}
    await again.send(*[ev(instance_key=f"f{i}", session_id=f"t{i}") for i in range(10)])
    assert len(again.sender.calls) == 5


async def test_sms_day_count_reads_a_corrupt_file_as_empty(tmp_path) -> None:
    (tmp_path / "notification_sms_day_count.json").write_text("{not json")
    counts = SmsDayCount(tmp_path)
    assert counts.used(D1, "2026-10-03") == 0
    counts.add(D1, "2026-10-03", 3)
    assert SmsDayCount(tmp_path).used(D1, "2026-10-03") == 3 and SmsDayCount(tmp_path).used(D1, "2026-10-04") == 0
