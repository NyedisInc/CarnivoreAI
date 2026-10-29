
from __future__ import annotations

import asyncio
from unittest import mock

import pytest

from src.core.notifications import delivery, engine as eng, routing_view
from src.core.notifications.contracts import FailureClass as F, NotifyEvent
from tests.python.notifications.engine_fakes import (
    LATE, NOON, OK, QUIET_NIGHT, Clock, FakeSender, FakeView, FakeWriter, Screens, Sleeper, dest, ev, fail,
)

pytestmark = pytest.mark.asyncio


class Rig:

    def __init__(self, dests, *, ticks=None, paused=False, sender=None, muted=(), screen=False, manual=False,
                 now=NOON, base="https://x.example", uuid_muted=(), sms_state_dir=None) -> None:
        self.clock = Clock(now)
        self.sleep = Sleeper(self.clock, manual=manual)
        self.view = FakeView(dests, ticks, paused)
        self.writer = FakeWriter()
        self.sender = sender or FakeSender()
        self.screens = Screens(screen)
        self.muted = set(muted)
        self.uuid_muted = set(uuid_muted)
        self.secret = {"k": "v"}

        async def secrets(dest_id):
            return self.secret

        async def link_base():
            return base

        self.engine = eng.NotifyEngine(
            sender_lookup=lambda kind: self.sender, is_muted=lambda sid: sid in self.muted, secrets_lookup=secrets,
            link_base=link_base, computer_name=lambda: "hostb", clock=self.clock, sleep=self.sleep,
            screens=self.screens, is_uuid_muted=lambda u: u in self.uuid_muted, sms_state_dir=sms_state_dir)
        routing_view.install_routing(lambda: self.view, self.writer)

    async def send(self, *events: NotifyEvent) -> None:
        for e in events:
            await self.engine.handle(e)
        await self.engine.join()


@pytest.fixture(autouse=True)
def _clean():
    routing_view.uninstall_routing()
    eng.install_engine(None)
    yield
    routing_view.uninstall_routing()
    eng.install_engine(None)


@pytest.fixture(autouse=True)
def _no_alert():
    with mock.patch.object(eng.alert_service, "raise_alert") as m, mock.patch.object(eng.resource_push, "notify"):
        yield m


async def test_delivers_with_computer_and_link():
    r = Rig([dest()])
    await r.send(ev())
    (event, config, secrets), = r.sender.calls
    assert event.computer == "hostb" and event.link.startswith("https://x.example/session/")
    assert secrets == {"k": "v"}


async def test_sender_gets_dest_id_and_details_in_config():
    r = Rig([dest(1, details=True, config={"url": "u"}), dest(2, kind="webpush")])
    await r.send(ev())
    by = {c[1]["dest_id"]: c for c in r.sender.calls}
    assert by["d_000000000001"][1] == {"url": "u", "dest_id": "d_000000000001", "details": True}
    assert by["d_000000000002"][1]["details"] is False and by["d_000000000002"][2] == {}


async def test_missing_or_unavailable_secrets_get_their_own_uncounted_class():
    from src.core.notifications.destinations.secrets import SecretStoreUnavailable

    for lookup, klass in ((None, "secret_missing"), (SecretStoreUnavailable("x"), "keychain_locked")):
        r = Rig([dest()])

        async def secrets(_, lookup=lookup):
            if lookup is None:
                return None
            raise lookup

        r.engine._secrets_lookup = secrets
        await r.send(ev())
        assert r.sender.calls == [] and r.sleep.calls == []
        assert r.engine.statuses()["d_000000000001"].last_failure == klass
        await r.send(ev())
        assert r.engine.statuses()["d_000000000001"].consecutive_permanent_failures == 0


async def test_five_secret_failures_do_not_disable_and_delivery_resumes_when_the_secret_appears(_no_alert):
    r = Rig([dest()])
    present = {"on": False}

    async def secrets(_):
        return {"k": "v"} if present["on"] else None

    r.engine._secrets_lookup = secrets
    for i in range(6):
        await r.send(ev(instance_key=f"k{i}", session_id=f"ses_{i}"))
    st = r.engine.statuses()["d_000000000001"]
    assert r.writer.disabled == [] and st.disabled_reason is None and st.consecutive_permanent_failures == 0
    assert _no_alert.call_count == 0 and r.sender.calls == []
    present["on"] = True
    await r.send(ev(instance_key="after", session_id="ses_after"))
    assert len(r.sender.calls) == 1


async def test_no_double_send_same_event_and_same_toast_version():
    r = Rig([dest(reminder_minutes=0)])
    e = ev(instance_key="same", session_id="ses_a")
    await r.send(e, e)
    assert len(r.sender.calls) == 1
    t1 = ev("session.question", toast_id="t1", toast_version=2, instance_key="", session_id="ses_b")
    t2 = ev("session.question", toast_id="t1", toast_version=2, instance_key="", session_id="ses_b")
    await r.send(t1, t2)
    assert len(r.sender.calls) == 2
    t3 = ev("session.question", toast_id="t1", toast_version=3, instance_key="", session_id="ses_b")
    await r.send(t3)
    assert len(r.sender.calls) == 3
    r.clock.now += 301
    await r.send(e)
    assert len(r.sender.calls) == 4


async def test_cooldown_per_type_and_session_and_needs_you_bypass():
    r = Rig([dest()])
    await r.send(ev(session_id="s1", instance_key="a"), ev(session_id="s1", instance_key="b"))
    assert len(r.sender.calls) == 1
    await r.send(ev(session_id="s2", instance_key="c"))
    assert len(r.sender.calls) == 2
    r.clock.now += 11
    await r.send(ev(session_id="s1", instance_key="d"))
    assert len(r.sender.calls) == 3
    await r.send(ev("session.permission", session_id="s1", instance_key="p1"),
                 ev("session.permission", session_id="s1", instance_key="p2"))
    assert len(r.sender.calls) == 5


async def test_sessionless_question_climbs_in_one_burst_are_not_merged_by_the_cooldown():
    r = Rig([dest()])
    q = lambda n: ev("swarm.question_climbed", instance_key=f"question:{n}", session_id=None, tmux_name=None)  # noqa: E731
    first = q(1)
    await r.send(first, q(2), first)
    assert len(r.sender.calls) == 2


async def test_mute_outranks_everything():
    r = Rig([dest()], muted={"ses_m"})
    await r.send(ev("session.permission", session_id="ses_m"))
    assert r.sender.calls == []


async def test_f9_peer_origin_and_remote_ids_refused():
    r = Rig([dest()])
    await r.send(ev(origin="peer"), ev(session_id="remote:peer-1"))
    assert r.sender.calls == []


async def test_pause_and_unregistered_type_and_untick_and_disabled():
    r = Rig([dest()], paused=True)
    await r.send(ev())
    assert r.sender.calls == []
    r = Rig([dest()])
    await r.send(ev("not.a.type"))
    assert r.sender.calls == []
    r = Rig([dest()], ticks={("d_000000000001", "session.finished"): False})
    await r.send(ev())
    assert r.sender.calls == []
    r = Rig([dest(enabled=False)])
    await r.send(ev())
    assert r.sender.calls == []


async def test_no_view_installed_drops():
    r = Rig([dest()])
    routing_view.uninstall_routing()
    await r.send(ev())
    assert r.sender.calls == []


@pytest.mark.parametrize("failure,retries", [(F.TIMEOUT, 2), (F.NETWORK, 2), (F.SERVER, 2), (F.RATE_LIMITED, 2),
                                             (F.AUTH, 0), (F.GONE, 0), (F.INVALID, 0), (F.BLOCKED, 0)])
async def test_retry_classes(failure, retries):
    r = Rig([dest()], sender=FakeSender(*[fail(failure)] * 3))
    await r.send(ev())
    assert len(r.sender.calls) == 1 + retries
    assert r.sleep.calls == [1.0, 4.0][:retries]


async def test_retry_succeeds_midway_and_retry_after_is_capped():
    r = Rig([dest()], sender=FakeSender(fail(F.RATE_LIMITED, retry_after=7.0), fail(F.RATE_LIMITED, retry_after=300.0),
                                        OK))
    await r.send(ev())
    assert len(r.sender.calls) == 3 and r.sleep.calls == [7.0, 20.0]
    assert r.engine.statuses()["d_000000000001"].last_ok_ts == NOON + 27.0


async def test_queue_overflow_drops_oldest():
    r = Rig([dest()])
    gate = asyncio.Event()
    order = []

    async def slow_send(event, config, secrets):
        order.append(event.instance_key)
        await gate.wait()
        return OK

    r.sender.send = slow_send
    events = [ev(instance_key=f"e{i}", session_id=f"s{i}") for i in range(52)]
    await r.engine.handle(events[0])
    await asyncio.sleep(0)
    for e in events[1:]:
        await r.engine.handle(e)
    gate.set()
    await r.engine.join()
    assert order[0] == "e0" and "e1" not in order and len(order) == 51 and order[-1] == "e51"


async def test_twenty_per_minute():
    r = Rig([dest()])
    await r.send(*[ev(instance_key=f"e{i}", session_id=f"s{i}") for i in range(25)])
    assert len(r.sender.calls) == 25
    assert len(r.sleep.calls) == 1 and 0 < r.sleep.calls[0] <= 60


async def test_sms_twenty_per_day():
    r = Rig([dest(kind="twilio")])
    r.secret = {"numbers": "+15550000001"}
    await r.send(*[ev(instance_key=f"e{i}", session_id=f"s{i}") for i in range(25)])
    assert len(r.sender.calls) == 20
    r.clock.now += 86401
    await r.send(ev(instance_key="late", session_id="sx"))
    assert len(r.sender.calls) == 21


async def test_sms_cap_counts_billed_messages_not_sends():
    r = Rig([dest(kind="twilio")])
    r.secret = {"numbers": "+15550000001\n+15550000002\n+15550000003"}
    await r.send(*[ev(instance_key=f"e{i}", session_id=f"s{i}") for i in range(9)])
    assert len(r.sender.calls) == 6
    st = r.engine.statuses()["d_000000000001"]
    assert st.last_failure == "rate_limited" and st.consecutive_permanent_failures == 0 and not st.disabled_reason
    assert r.writer.disabled == []
    r.clock.now += 86401
    await r.send(ev(instance_key="late", session_id="sx"))
    assert len(r.sender.calls) == 7


async def test_five_permanent_failures_disable_and_raise_one_alert(_no_alert):
    r = Rig([dest()], sender=FakeSender(*[fail(F.AUTH, status_code=401)] * 20))
    await r.send(*[ev(instance_key=f"e{i}", session_id=f"s{i}") for i in range(8)])
    assert r.writer.disabled and len(r.writer.disabled) == 1 and r.writer.disabled[0][0] == "d_000000000001"
    assert _no_alert.call_count == 1 and _no_alert.call_args.args[0] == "notifications.destination_disabled"
    assert len(r.sender.calls) == 5
    st = r.engine.statuses()["d_000000000001"]
    assert st.disabled_reason and st.last_failure == "auth"


@pytest.mark.parametrize("klass", [F.PRIVATE_OFF, F.PLAIN_HTTP_OFF, F.ORIGIN_CHANGED])
async def test_this_computers_local_policy_never_counts_toward_the_auto_disable(klass, _no_alert):
    r = Rig([dest()], sender=FakeSender(*[fail(klass)] * 20))
    await r.send(*[ev(instance_key=f"e{i}", session_id=f"s{i}") for i in range(8)])
    st = r.engine.statuses()["d_000000000001"]
    assert not r.writer.disabled and _no_alert.call_count == 0 and not st.disabled_reason
    assert st.last_failure == klass.value and st.consecutive_permanent_failures == 0
    assert len(r.sender.calls) == 8 and r.sleep.calls == []


async def test_success_resets_permanent_count_and_retryable_does_not_count():
    r = Rig([dest()], sender=FakeSender(*([fail(F.AUTH)] * 4), OK, *([fail(F.AUTH)] * 4)))
    await r.send(*[ev(instance_key=f"e{i}", session_id=f"s{i}") for i in range(9)])
    assert r.writer.disabled == []
    r = Rig([dest()], sender=FakeSender(*([fail(F.SERVER)] * 30)))
    await r.send(*[ev(instance_key=f"e{i}", session_id=f"s{i}") for i in range(6)])
    assert r.writer.disabled == []


async def test_quiet_hours_needs_you_passes():
    r = Rig([dest(quiet=QUIET_NIGHT)], now=LATE)
    await r.send(ev(), ev("session.permission"))
    assert [c[0].type_id for c in r.sender.calls] == ["session.permission"]
    r = Rig([dest(quiet=QUIET_NIGHT)], now=NOON)
    await r.send(ev())
    assert len(r.sender.calls) == 1


async def test_project_filter_applies_only_to_events_with_a_project():
    r = Rig([dest(projects=("alpha",))])
    await r.send(ev(project="beta"), ev(project="alpha"), ev(project=""))
    assert sorted(c[0].project for c in r.sender.calls) == ["", "alpha"]


async def test_details_stripped_unless_destination_opts_in():
    r = Rig([dest(1, details=True), dest(2, details=False), dest(3, kind="twilio", details=True)])
    await r.send(ev(details="rm -rf"))
    got = {c[0].details for c in r.sender.calls}
    assert got == {"rm -rf", None} and len(r.sender.calls) == 3
    assert sum(1 for c in r.sender.calls if c[0].details) == 1


async def test_away_hold_then_sent_if_open_and_dropped_if_closed():
    r = Rig([dest(away=True)], screen=True, manual=True)
    await r.engine.handle(ev("session.question", instance_key="q1"))
    await asyncio.sleep(0)
    assert r.sender.calls == [] and r.sleep.waiting[0][0] == 120.0
    await r.sleep.release()
    await r.engine.join()
    assert len(r.sender.calls) == 1
    r2 = Rig([dest(away=True)], screen=True, manual=True)
    r2.engine.register_open_check("session.question", lambda e: False)
    await r2.engine.handle(ev("session.question", instance_key="q2"))
    await r2.sleep.release()
    await r2.engine.join()
    assert r2.sender.calls == []


async def test_away_no_screen_sends_at_once():
    r = Rig([dest(away=True)], screen=False)
    await r.send(ev())
    assert len(r.sender.calls) == 1


async def test_reminder_exactly_once_and_only_if_open():
    r = Rig([dest(reminder_minutes=10)], manual=True)
    await r.engine.handle(ev("session.permission", instance_key="p"))
    await r.engine.join()
    assert len(r.sender.calls) == 1 and r.sleep.waiting[0][0] == 600.0
    await r.sleep.release()
    await r.engine.join()
    assert len(r.sender.calls) == 2
    await r.sleep.release()
    await r.engine.join()
    assert len(r.sender.calls) == 2
    r2 = Rig([dest()], manual=True)
    r2.engine.register_open_check("session.permission", lambda e: False)
    await r2.engine.handle(ev("session.permission"))
    await r2.engine.join()
    await r2.sleep.release()
    await r2.engine.join()
    assert len(r2.sender.calls) == 1
    r3 = Rig([dest()], manual=True)
    await r3.engine.handle(ev())
    await r3.engine.join()
    assert r3.sleep.waiting == []


async def test_send_test_bypasses_everything_and_is_limited():
    r = Rig([dest(enabled=False, quiet=QUIET_NIGHT)], ticks={("d_000000000001", "alert.other"): False}, paused=True,
            now=LATE)
    out = await r.engine.send_test("d_000000000001")
    assert out.found and not out.limited and out.result.ok and r.sender.calls[0][0].kind == "test"
    again = await r.engine.send_test("d_000000000001")
    assert again.limited and len(r.sender.calls) == 1
    r.clock.now += 11
    assert not (await r.engine.send_test("d_000000000001")).limited
    assert (await r.engine.send_test("d_nope")).found is False


async def test_status_published_and_provider_installed(_no_alert):
    r = Rig([dest()], sender=FakeSender(fail(F.AUTH)))
    await r.engine.start()
    await r.send(ev())
    await asyncio.sleep(0)
    assert routing_view.current_statuses()["d_000000000001"].last_failure == "auth"
    eng.resource_push.notify.assert_called_with("notification_settings")
    await r.engine.stop()


async def test_offer_hops_from_another_thread():
    r = Rig([dest()])
    await r.engine.start()
    await asyncio.to_thread(r.engine.offer, ev())
    for _ in range(20):
        await asyncio.sleep(0)
        await r.engine.join()
    assert len(r.sender.calls) == 1
    await r.engine.stop()
    r.engine.offer(ev())


async def test_delivery_retry_delay_table():
    assert delivery.retry_delay(fail(F.RATE_LIMITED, retry_after=3), 0) == 3.0
    assert delivery.retry_delay(fail(F.SERVER), 1) == 4.0


async def _backlogged(r: Rig, n: int = 21) -> list:
    events = [ev(instance_key=f"q{i}", session_id=f"s{i}") for i in range(n)]
    for e in events:
        await r.engine.handle(e)
    for _ in range(20):
        await asyncio.sleep(0)
    assert len(r.sender.calls) == 20 and r.sleep.waiting
    return events


async def test_item_queued_before_a_mute_is_not_sent():
    r = Rig([dest()], manual=True)
    events = await _backlogged(r)
    r.muted.add(events[-1].session_id)
    await r.sleep.release()
    await r.engine.join()
    assert len(r.sender.calls) == 20


async def test_item_queued_before_a_pause_is_not_sent():
    r = Rig([dest()], manual=True)
    await _backlogged(r)
    r.view.paused = True
    await r.sleep.release()
    await r.engine.join()
    assert len(r.sender.calls) == 20


async def test_backlogged_item_still_sends_when_nothing_changed():
    r = Rig([dest()], manual=True)
    await _backlogged(r)
    await r.sleep.release()
    await r.engine.join()
    assert len(r.sender.calls) == 21


async def test_admit_refuses_a_peer_owned_item_and_a_closed_held_item():
    r = Rig([dest()])
    d = dest()
    assert r.engine._admit(delivery.Item(d, ev()))
    assert not r.engine._admit(delivery.Item(d, ev(session_id="remote:peer-1")))
    assert not r.engine._admit(delivery.Item(d, ev(origin="peer")))
    r.engine.register_open_check("session.question", lambda e: False)
    assert not r.engine._admit(delivery.Item(d, ev("session.question"), recheck_open=True))
    assert r.engine._admit(delivery.Item(d, ev("session.question")))


async def test_retry_is_dropped_when_muted_during_the_backoff():
    muted: set = set()

    class MutesOnFirstSend(FakeSender):
        async def send(self, event, config, secrets):
            muted.add(event.session_id)
            return await super().send(event, config, secrets)

    r = Rig([dest()], sender=MutesOnFirstSend(fail(F.TIMEOUT)))
    r.muted = muted
    await r.send(ev(session_id="s_retry"))
    assert len(r.sender.calls) == 1
