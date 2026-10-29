import subprocess

import pytest

from src.core.machine_stats import cpu_busy
from src.core.pack.placement import rule
from src.core.pack.transport import bundles
from src.core.swarm import admission


class _Ticks:

    def __init__(self):
        self.now, self.busy, self.total = 0.0, 0, 0

    def step(self, share, seconds=100.0):
        self.now += seconds
        self.total += int(seconds * 1000)
        self.busy += int(seconds * 1000 * share)

    def meter(self):
        return cpu_busy.CpuMeter(read=lambda: (self.busy, self.total), clock=lambda: self.now)


def _measure(share, load=184.0):
    ticks = _Ticks()
    meter = ticks.meter()
    meter.sample()
    ticks.step(share)
    got = meter.busy_cores(10)
    return admission.Machine(load, load, 10, 60.0, 16.0, got["busy_1"], got["busy_5"]), got


def test_load_average_184_with_the_cpu_mostly_idle_is_not_pegged_and_has_headroom():
    machine, got = _measure(0.58)
    assert got["source"] == cpu_busy.SOURCE_TICKS and got["busy_1"] == pytest.approx(5.8, abs=0.1)
    assert admission.refusal(machine, 3, reserve=admission.Reserve(30, 20, "in_use")) is None
    head = rule.headroom({"load": {"cores": 10, "load_1": 184.0, "busy_cores": got["busy_1"], "mem_total_gb": 16, "mem_available_gb": 12},
                          "reserve": {"level": "in_use", "cpu_pct": 30, "mem_pct": 20}})
    assert head.cpu_cores == pytest.approx(1.2, abs=0.1) and head.load_per_core == pytest.approx(0.58, abs=0.01)
    idle = rule.headroom({"load": {"cores": 10, "load_1": 184.0, "busy_cores": 1.0, "mem_total_gb": 16, "mem_available_gb": 12},
                          "reserve": {"level": "away", "cpu_pct": 10, "mem_pct": 10}})
    assert idle.cpu_cores == pytest.approx(8.0)


def test_a_fully_busy_cpu_is_pegged_and_no_tick_delta_falls_back_to_the_load_average():
    machine, _ = _measure(0.98, load=3.0)
    said = admission.refusal(machine, 3)
    assert said and said.startswith(admission.PEGGED) and "98% busy" in said
    assert admission.refusal(admission.Machine(184.0, 184.0, 10, 60.0), 0) is not None
    assert cpu_busy.CpuMeter(read=lambda: None).busy_cores(10) == {"busy_1": None, "busy_5": None, "source": cpu_busy.SOURCE_LOAD}


def test_a_detached_home_head_still_carries_a_branch(tmp_path):
    def g(*args):
        return subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    g("init", "-q", "-b", "trunk")
    (tmp_path / "a").write_text("1")
    g("add", "a")
    g("commit", "-q", "-m", "one")
    g("checkout", "-q", "--detach")
    assert bundles.current_branch(str(tmp_path)) is None
    assert bundles.carry_branch(str(tmp_path)) == "trunk"
    (tmp_path / "a").write_text("2")
    g("commit", "-q", "-am", "two")
    with pytest.raises(bundles.BundleError) as err:
        bundles.carry_branch(str(tmp_path))
    assert err.value.code == "detached_head_no_branch"
    g("update-ref", "refs/remotes/origin/main", "HEAD")
    g("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    assert bundles.carry_branch(str(tmp_path)) == "main"
