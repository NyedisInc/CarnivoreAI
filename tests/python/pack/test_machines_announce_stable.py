
from __future__ import annotations

from datetime import datetime

from src.core.pack.machines import config_state, exchange, roster
from tests.python.pack.test_machines_roster import FakeCollector


def _runtime(tmp_path, clock):
    path = tmp_path / "a.json"
    path.write_text("{}")
    named: list = []
    rt = exchange.PackMachines(
        install_id="install-a", label="mac", app_version="1.0", state=config_state.ConfigState(lambda: path),
        collector=FakeCollector("a"), default_master=lambda: "install-a", connected=lambda: [],
        notify=lambda topic, key, every: named.append((topic, key)), clock=clock,
        local_now=lambda: datetime(2026, 10, 28, 3, 0))
    return rt, named


def _snap(cpu=5.0, level="normal", offers=()):
    return {"load": {"cpu_percent": cpu, "memory_percent": 40.0, "disk_percent": 50.0, "load_1": 1.0},
            "reserve": {"level": level, "config": {}}, "battery": None, "restrictions": {}, "credential_offers": list(offers)}


def test_load_only_changes_wait_for_the_slow_cadence_and_stable_changes_name_the_topic_at_once(tmp_path):
    now = [1000.0]
    rt, named = _runtime(tmp_path, lambda: now[0])
    rt._arm_stale_notice = lambda _i: None
    rt._announce("b", _snap(cpu=5.0), roster.STATE_CONNECTED)
    assert len(named) == 1, "the first snapshot names the topic"
    now[0] += 6
    rt._announce("b", _snap(cpu=40.0), roster.STATE_CONNECTED)
    assert len(named) == 1, "RED WHEN: a load-only change inside the slow window names the topic"
    now[0] += 6
    rt._announce("b", _snap(cpu=5.0), roster.STATE_CONNECTED)
    assert len(named) == 1, "an identical snapshot is silent"
    rt._announce("b", _snap(cpu=5.0, level="reserved"), roster.STATE_CONNECTED)
    assert len(named) == 2, "RED WHEN: a stable-part change (reserve level) waits for the cadence"
    rt._announce("b", _snap(cpu=5.0, level="reserved"), roster.STATE_STALE)
    assert len(named) == 3, "a state word change names it at once"
    rt._announce("b", _snap(cpu=5.0, level="reserved", offers=[{"x": 1}]), roster.STATE_STALE)
    assert len(named) == 4
    now[0] += exchange.LOAD_NOTIFY_SECONDS
    rt._announce("b", _snap(cpu=80.0, level="reserved", offers=[{"x": 1}]), roster.STATE_STALE)
    assert len(named) == 5, "RED WHEN: load never refreshes after the slow window (the display would go stale)"
