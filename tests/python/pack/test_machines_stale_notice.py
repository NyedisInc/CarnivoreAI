
from __future__ import annotations

import threading
from datetime import datetime

from src.core.pack.machines import config_state, exchange, roster
from tests.python.pack.test_machines_roster import FakeCollector


def test_a_silent_peer_names_the_topic_after_the_stale_boundary_and_a_new_snapshot_rearms(tmp_path, monkeypatch):
    monkeypatch.setattr(roster, "STALE_SECONDS", -0.9)
    path = tmp_path / "a.json"
    path.write_text("{}")
    named, fired = [], threading.Event()
    rt = exchange.PackMachines(
        install_id="install-a", label="mac", app_version="1.0", state=config_state.ConfigState(lambda: path),
        collector=FakeCollector("a"), default_master=lambda: "install-a", connected=lambda: [],
        notify=lambda topic, key, every: (named.append((topic, key)), fired.set()),
        local_now=lambda: datetime(2026, 10, 10, 3, 0))
    rt._arm_stale_notice("install-b")
    first = rt._stale_timers["install-b"]
    rt._arm_stale_notice("install-b")
    assert first is not rt._stale_timers["install-b"], "a new snapshot replaces the timer"
    assert fired.wait(2.0), "the topic was named with nothing written"
    assert named == [(exchange.TOPIC, "install-b")], "one notice: the replaced timer never fires"
