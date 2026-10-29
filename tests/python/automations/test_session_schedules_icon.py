
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import src.config  # noqa: F401
from src.api import automation_timers_listing as listing
from src.core.automations import plugin_schedules
from src.cplugs.sdk import ports
from src.models import SessionInfo

AUTO = {"automation_id": "a", "name": "nightly", "enabled": True, "retry_due_at": None, "next_fire_at": 500.0,
        "target": {"kind": "session_message", "session_uuid": "u1"}}


class Store:
    def __init__(self, automations=()):
        self._automations = list(automations)

    def list_all(self):
        return self._automations

    def latest_stopped_runs(self):
        return {}


class Port:
    def __init__(self, by_session=None, error=None):
        self.by, self.error = by_session or {}, error

    async def by_session(self, infos):
        if self.error:
            raise self.error
        return self.by


def entry(name="sweep", fire=900.0, enabled=True, failed=False, retrying=False):
    return {"name": name, "next_fire_at": fire, "enabled": enabled, "failed": failed, "retrying": retrying}


@pytest.fixture(autouse=True)
def clean_ports(monkeypatch):
    monkeypatch.setattr(listing, "_row_ids", lambda uuids: {"u1": 7})
    ports.unregister(plugin_schedules.PORT)
    yield
    ports.unregister(plugin_schedules.PORT)


def stamp(entries=None, automations=(), port="on", error=None):
    if port == "on":
        ports.register(plugin_schedules.PORT, Port({"ses_x": entries or []}, error))
    info = SessionInfo.model_construct(host_key="local", origin_install_id=None, session_row_id=7, session=SimpleNamespace(id="ses_x"),
                                       automations_state="stale")
    asyncio.run(listing.mark_automation_timers(SimpleNamespace(automation_store=Store(automations)), [info]))
    return info


def test_one_schedule_and_no_automations_is_green():
    info = stamp([entry()])
    assert (info.automations_state, info.automations_total, info.automations_enabled) == ("ok", 1, 1)
    assert [(m.name, m.next_fire_at, m.enabled) for m in info.automations_next] == [("sweep", 900.0, True)]


def test_a_paused_schedule_is_gray():
    info = stamp([entry(enabled=False)])
    assert (info.automations_state, info.automations_total, info.automations_enabled) == ("disabled", 1, 0)
    assert info.automations_next[0].next_fire_at is None


def test_a_failed_fire_is_yellow_when_it_carries_on_and_red_when_it_does_not():
    assert stamp([entry(), entry("again", failed=True, retrying=True)], [AUTO]).automations_state == "warning"
    assert stamp([entry("once", failed=True)], [AUTO]).automations_state == "error"


def test_automations_and_schedules_roll_up_together_soonest_first():
    info = stamp([entry("late", 900.0), entry("early", 100.0)], [AUTO])
    assert (info.automations_state, info.automations_total, info.automations_enabled) == ("ok", 3, 3)
    assert [m.name for m in info.automations_next] == ["early", "nightly", "late"]


def test_the_tooltip_list_is_capped_but_the_count_is_whole():
    info = stamp([entry(f"s{n}", float(n)) for n in range(listing.MAX_MARKS + 3)])
    assert len(info.automations_next) == listing.MAX_MARKS and info.automations_total == listing.MAX_MARKS + 3


def test_with_the_plugin_off_the_icon_counts_automations_only():
    info = stamp(port="off", automations=[AUTO])
    assert (info.automations_state, info.automations_total) == ("ok", 1)
    assert [m.name for m in info.automations_next] == ["nightly"]
    assert stamp(port="off").automations_state == "none"


def test_a_plugin_that_cannot_read_is_not_measured_not_partial():
    info = stamp(error=OSError("locked"), automations=[AUTO])
    assert (info.automations_state, info.automations_total, info.automations_enabled, info.automations_next) == (None, None, None, None)
