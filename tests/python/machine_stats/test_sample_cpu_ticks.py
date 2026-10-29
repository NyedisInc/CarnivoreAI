
from typing import List, Optional, Tuple

from src.core.machine_stats import sample

Ticks = Optional[Tuple[int, int]]


def _sampler(ticks: List[Ticks], step: float = 10.0) -> sample.MachineSampler:
    feed = iter(ticks)
    now = [0.0]

    def read_ticks() -> Ticks:
        now[0] += step
        return next(feed)

    return sample.MachineSampler(lambda: "/", clock=lambda: now[0], read_ticks=read_ticks)


def test_first_read_is_unmeasured_then_busy_share() -> None:
    sampler = _sampler([(100, 1000), (150, 1100), (150, 1200)])
    assert sampler.read(0.0)["cpu_percent"] is None
    assert sampler.read(0.0)["cpu_percent"] == 50.0
    assert sampler.read(0.0)["cpu_percent"] == 0.0


def test_second_read_at_the_same_clock_time_is_none() -> None:
    sampler = _sampler([(100, 1000), (1100, 1100)], step=0.0)
    sampler.read(0.0)
    assert sampler.read(0.0)["cpu_percent"] is None


def test_unreadable_baseline_gives_none_then_recovers() -> None:
    sampler = _sampler([None, (100, 1000), (150, 1100)])
    assert sampler.read(0.0)["cpu_percent"] is None
    assert sampler.read(0.0)["cpu_percent"] is None
    assert sampler.read(0.0)["cpu_percent"] == 50.0


def test_reset_makes_the_next_read_unmeasured() -> None:
    sampler = _sampler([(100, 1000), (150, 1100), (160, 1200)])
    sampler.read(0.0)
    sampler.read(0.0)
    sampler.reset_cpu_baseline()
    assert sampler.read(0.0)["cpu_percent"] is None
