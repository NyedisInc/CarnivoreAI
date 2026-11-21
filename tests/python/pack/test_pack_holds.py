
import threading

from src.core.pack.reserve.holds import MAX_ENTRIES, Holds


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def room(limit_cpu: float, need: float = 1.0):
    return lambda cpu, ram: cpu + need <= limit_cpu


def test_two_threads_race_for_the_last_room_one_wins():
    holds, results, barrier = Holds(Clock()), [], threading.Barrier(2)

    def go(key: str) -> None:
        barrier.wait()
        results.append(holds.try_hold(key, "a", 1.0, 1.0, 120.0, room(1.0)))

    threads = [threading.Thread(target=go, args=(k,)) for k in ("j1", "j2")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [False, True]
    assert holds.total() == (1.0, 1.0, 1)


def test_expiry_extend_and_drop():
    clock = Clock()
    holds = Holds(clock)
    assert holds.try_hold("j", "a", 2.0, 3.0, 10.0, room(8.0, 2.0))
    clock.now = 9.0
    assert holds.extend("j", 10.0) and holds.total() == (2.0, 3.0, 1)
    clock.now = 18.0
    assert holds.total()[2] == 1
    clock.now = 19.5
    assert holds.total() == (0.0, 0.0, 0) and not holds.extend("j", 10.0)
    assert holds.try_hold("k", "a", 1.0, 1.0, 10.0, room(8.0))
    holds.drop("k")
    holds.drop("k")
    assert holds.total()[2] == 0


def test_total_excludes_one_key_and_a_rehold_replaces_not_doubles():
    holds = Holds(Clock())
    holds.try_hold("a", "x", 2.0, 1.0, 100.0, room(9.0, 2.0))
    holds.try_hold("b", "x", 3.0, 2.0, 100.0, room(9.0, 3.0))
    assert holds.total(exclude="a") == (3.0, 2.0, 1)
    assert holds.try_hold("a", "x", 2.0, 1.0, 100.0, room(5.0, 2.0))
    assert holds.total() == (5.0, 3.0, 2)


def test_no_cap_per_owner_and_a_full_table_is_no_room():
    holds = Holds(Clock())
    for i in range(MAX_ENTRIES):
        assert holds.try_hold(f"j{i}", "same-owner", 0.01, 0.0, 100.0, lambda c, r: True)
    assert not holds.try_hold("overflow", "same-owner", 0.01, 0.0, 100.0, lambda c, r: True)
    assert holds.try_hold("j0", "same-owner", 0.02, 0.0, 100.0, lambda c, r: True)
    assert not hasattr(holds, "count_for")


def test_a_fits_that_reads_the_totals_back_does_not_deadlock_and_bad_numbers_are_refused() -> None:
    holds = Holds(Clock())
    assert holds.try_hold("a", "o", 1, 1, 60, lambda c, r: holds.total()[0] + 1 <= 4) is True
    for cpu, ram, ttl in ((-1000, 1, 60), (1, -1, 60), (float("nan"), 1, 60), (1, float("inf"), 60), (1, 1, float("nan")), (1, 1, 0), (1, 1, -5)):
        assert holds.try_hold("b", "o", cpu, ram, ttl, lambda c, r: True) is False, (cpu, ram, ttl)
    assert holds.total() == (1.0, 1.0, 1)
