
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import src.config  # noqa: F401
from src.api import asleep_wake_listing
from src.core import resource_push
from src.core.automations import pause, plugin_schedules, wake_schedule
from src.core.resource_push import topics
from src.cplugs.sdk import ports
from src.models.records import SessionRecord


def auto(uuid="u1", due=500.0, enabled=True, if_asleep="wake", retry=None, kind="session_message"):
    return {"automation_id": "a", "name": "n", "enabled": enabled, "next_fire_at": due, "retry_due_at": retry,
            "target": {"kind": kind, "session_uuid": uuid, "if_asleep": if_asleep}}


def record(uuid="u1", asleep=True, archived=None, project=3) -> SessionRecord:
    return SessionRecord(session_uuid=uuid, origin="created", owned=True, lifecycle="stopped", project_attribution="explicit",
                         asleep=asleep, archived_at=archived, project_id=project)


class Store:
    def __init__(self, *automations):
        self.rows = list(automations)

    def list_all(self):
        return self.rows

    def latest_stopped_runs(self):
        return {}


class Port:
    def __init__(self, found=None, error=None):
        self.found, self.error, self.calls = found or {}, error, []

    async def wake_entries(self, asleep, infos=None, app_state=None):
        self.calls.append(asleep)
        if self.error:
            raise self.error
        return {u: [{"name": "tm", "next_fire_at": at, "enabled": True, "failed": False, "retrying": False}] for u, at in self.found.items()}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    ports.unregister(plugin_schedules.PORT)
    monkeypatch.setattr(pause, "is_paused", lambda *a, **k: False)
    yield
    ports.unregister(plugin_schedules.PORT)


def stamp(records, *automations, port=None):
    if port is not None:
        ports.register(plugin_schedules.PORT, port)
    state = SimpleNamespace(automation_store=Store(*automations))
    asyncio.run(asleep_wake_listing.stamp_next_wake(state, records))
    return [r.next_wake_at for r in records]


def test_an_automation_aimed_at_a_sleeping_session_sets_its_next_wake():
    assert stamp([record()], auto(due=500.0)) == [500.0]


def test_a_pending_retry_before_the_next_slot_is_the_wake():
    assert stamp([record()], auto(due=900.0, retry=600.0)) == [600.0]


@pytest.mark.parametrize("row", [auto(if_asleep="skip"), auto(enabled=False), auto(due=None), auto(kind="command"), auto(uuid="other")])
def test_an_automation_that_will_not_wake_it_leaves_none(row):
    assert stamp([record()], row) == [None]


def test_an_asleep_row_with_a_waking_schedule_carries_the_alarm_icon_words_and_one_without_does_not():
    woken, quiet = record("u1"), record("u2")
    stamp([woken, quiet], auto("u1", due=500.0), port=Port({"u1": 300.0}))
    assert (woken.automations_state, woken.automations_total, woken.automations_enabled) == ("ok", 2, 2)
    assert [m.name for m in woken.automations_next] == ["tm", "n"]
    assert (quiet.automations_state, quiet.automations_total, quiet.automations_next) == ("none", 0, [])


def test_the_alarm_icon_ignores_what_will_not_wake_the_session_and_is_null_when_a_source_is_unreadable():
    skipped, unread = record("u1"), record("u1")
    stamp([skipped], auto(if_asleep="skip"))
    assert skipped.automations_state == "none"
    stamp([unread], auto(), port=Port(error=RuntimeError("boom")))
    assert unread.automations_state is None and unread.automations_total is None and unread.next_wake_at == 500.0


def test_a_live_or_archived_record_gets_none_and_a_stale_value_is_cleared():
    live, archived, stale = record("u1", asleep=False), record("u1", archived="2026-01-01"), record("u2")
    stale.next_wake_at = 123.0
    assert stamp([live, archived, stale], auto("u1")) == [None, None, None]


def test_the_earliest_of_an_automation_and_a_plugin_schedule_wins_and_one_port_call_covers_every_row():
    port = Port({"u1": 300.0, "u2": 800.0})
    assert stamp([record("u1"), record("u2")], auto("u1", due=500.0), port=port) == [300.0, 800.0]
    assert len(port.calls) == 1 and [w["session_uuid"] for w in port.calls[0]] == ["u1", "u2"]


def test_an_unreadable_plugin_costs_only_its_own_source():
    assert stamp([record()], auto(due=500.0), port=Port(error=RuntimeError("boom"))) == [500.0]


def test_a_paused_scheduler_promises_no_automation_wake(monkeypatch):
    monkeypatch.setattr(pause, "is_paused", lambda *a, **k: True)
    assert stamp([record()], auto()) == [None]


def test_the_rule_never_returns_zero():
    assert wake_schedule.waking_automations([auto(due=0.0)], ["u1"]) == {}


def test_an_automation_write_wakes_the_listing_through_the_topic_listener():
    called = []
    remove = resource_push.add_topic_listener(topics.AUTOMATIONS, lambda: called.append(1))
    try:
        notifier = resource_push.install(lambda frame: 0, loop=asyncio.new_event_loop())
        notifier._pending.update({topics.AUTOMATIONS, topics.LAYOUTS})
        notifier.flush()
        notifier._pending.add(topics.LAYOUTS)
        notifier.flush()
    finally:
        remove()
        resource_push.uninstall()
    assert called == [1]
