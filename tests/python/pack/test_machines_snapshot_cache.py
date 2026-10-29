
from __future__ import annotations

import threading
from datetime import datetime

from src.core import host_metrics
from src.core.pack.machines import config_state, exchange
from tests.python.pack.test_machines_roster import FakeCollector


class CountingCollector(FakeCollector):

    def __init__(self) -> None:
        super().__init__("a")
        self.collects = 0

    def collect(self, **kwargs):
        self.collects += 1
        return super().collect(**kwargs)


def _runtime(tmp_path, clock, agents=None):
    path = tmp_path / "a.json"
    path.write_text("{}")
    collector = CountingCollector()
    rt = exchange.PackMachines(
        install_id="install-a", label="mac", app_version="1.0", state=config_state.ConfigState(lambda: path),
        collector=collector, default_master=lambda: "install-a", connected=lambda: [], notify=lambda *a: None,
        local_now=lambda: datetime(2026, 10, 10, 3, 0), clock=lambda: clock["t"], agents=agents)
    return rt, collector


def test_a_second_caller_inside_the_window_reuses_the_snapshot_and_expiry_rebuilds(tmp_path):
    clock = {"t": 1000.0}
    rt, collector = _runtime(tmp_path, clock)
    first = rt.own_snapshot()
    first["load"]["load_1"] = 99
    assert rt.own_snapshot()["load"]["load_1"] == 1.3 and collector.collects == 1
    clock["t"] += exchange.SNAPSHOT_TTL_SECONDS + 0.1
    rt.own_snapshot()
    assert collector.collects == 2


def test_concurrent_callers_share_one_build(tmp_path):
    clock = {"t": 1000.0}
    rt, collector = _runtime(tmp_path, clock)
    threads = [threading.Thread(target=rt.own_snapshot) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert collector.collects == 1


def test_an_owner_edit_and_a_new_agents_viewer_show_at_once(tmp_path):
    clock = {"t": 1000.0}
    calls = []
    rt, collector = _runtime(tmp_path, clock, agents=lambda: (calls.append(1), {"rows": []})[1])
    assert rt.own_snapshot()["agents"] is None and not calls
    rt.touch()
    assert rt.own_snapshot()["agents"] == {"rows": []} and len(calls) == 1
    rt.set_restrictions({"max_agents": 3}, from_peer=False)
    assert rt.own_snapshot()["restrictions"]["max_agents"] == 3 and collector.collects == 3


def test_boot_static_sysctls_are_read_once(monkeypatch):
    reads = []
    monkeypatch.setattr(host_metrics, "_BOOT_STATIC", {})
    monkeypatch.setattr(host_metrics, "_sysctl_int", lambda name: (reads.append(name), 17179869184)[1])
    assert host_metrics._static_sysctl_int("hw.memsize") == host_metrics._static_sysctl_int("hw.memsize") == 17179869184
    assert reads == ["hw.memsize"]
    monkeypatch.setattr(host_metrics, "_BOOT_STATIC", {})
    monkeypatch.setattr(host_metrics, "_sysctl_int", lambda name: None)
    assert host_metrics._static_sysctl_int("hw.memsize") is None and not host_metrics._BOOT_STATIC
