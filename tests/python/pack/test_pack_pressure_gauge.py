
from src.core.pack.reserve.holds import Holds
from src.core.pack.reserve.pressure import Gauge, parse_psi, read_mem_pressure, read_run_queue


class Rig:
    def __init__(self) -> None:
        self.now, self.figures, self.mem, self.rq, self.throttled = 0.0, (2.0, 7.0, 10), "normal", 0.2, 0
        self.holds = Holds(self.clock)
        self.gauge = Gauge(lambda: self.figures, lambda: self.mem, lambda: self.rq, lambda: self.throttled, self.holds,
                           self.clock, lambda: 1_000_000.0 + self.now)

    def clock(self) -> float:
        return self.now

    def tick(self, advance: float = 10.0) -> None:
        self.now += advance
        self.gauge.tick()


def test_calm_computer_is_not_pegged():
    rig = Rig()
    rig.tick()
    assert not rig.gauge.pegged() and rig.gauge.view()["why"] == ""


def test_over_the_line_pegs_and_clears_only_after_sixty_seconds_under_the_margin():
    rig = Rig()
    rig.figures = (7.5, 7.0, 10)
    rig.tick()
    assert rig.gauge.pegged() and "reserve line" in rig.gauge.view()["why"] and rig.gauge.view()["since"] is not None
    rig.figures = (6.8, 7.0, 10)
    rig.tick(70)
    assert rig.gauge.pegged()
    rig.figures = (3.0, 7.0, 10)
    rig.tick()
    rig.tick(50)
    assert rig.gauge.pegged()
    rig.tick(10)
    assert not rig.gauge.pegged() and rig.gauge.view()["since"] is None
    rig.figures = (7.5, 7.0, 10)
    rig.tick()
    rig.figures = (3.0, 7.0, 10)
    rig.tick(40)
    rig.figures = (7.5, 7.0, 10)
    rig.tick(10)
    rig.figures = (3.0, 7.0, 10)
    rig.tick(40)
    assert rig.gauge.pegged()


def test_run_queue_pegs_and_needs_under_1_2_to_clear():
    rig = Rig()
    rig.rq = 1.6
    rig.tick()
    assert rig.gauge.pegged() and "run queue" in rig.gauge.view()["why"]
    rig.rq = 1.3
    rig.tick(120)
    assert rig.gauge.pegged()
    rig.rq = 1.1
    rig.tick()
    rig.tick(60)
    assert not rig.gauge.pegged()


def test_memory_pressure_pegs_each_level_and_normal_clears():
    for word in ("warn", "critical"):
        rig = Rig()
        rig.mem = word
        rig.tick()
        assert rig.gauge.pegged() and word in rig.gauge.view()["why"]
        rig.mem = "normal"
        rig.tick()
        rig.tick(60)
        assert not rig.gauge.pegged()


def test_unknown_figures_never_peg_and_do_not_block_the_clear():
    rig = Rig()
    rig.figures, rig.mem, rig.rq = None, None, None
    rig.tick()
    assert not rig.gauge.pegged() and rig.gauge.view()["busy_cores"] is None
    rig.mem = "warn"
    rig.tick()
    assert rig.gauge.pegged()
    rig.mem = None
    rig.tick()
    rig.tick(60)
    assert not rig.gauge.pegged()


def test_view_publishes_held_and_the_real_throttled_count():
    rig = Rig()
    rig.holds.try_hold("j", "a", 2.0, 4.0, 100.0, lambda c, r: True)
    rig.throttled = 3
    rig.tick()
    view = rig.gauge.view()
    assert view["held"] == {"cpu": 2.0, "ram_gb": 4.0, "n": 1} and view["throttled"] == 3
    assert set(view) == {"pegged", "since", "why", "busy_cores", "line", "cores", "run_queue_per_core", "mem", "held", "throttled"}


def test_hour_book_rows_are_drained():
    rig = Rig()
    rig.figures = (8.0, 7.0, 10)
    for _ in range(6):
        rig.tick()
    rows = rig.gauge.hours()
    assert len(rows) == 1 and rows[0]["pegged_minutes"] == 1.0 and rows[0]["busy_pct"] == 80.0
    rig.now += 7200
    assert rig.gauge.hours()[0]["hour"] == rows[0]["hour"]
    assert rig.gauge.hours() == []


def test_psi_and_platform_reads():
    assert parse_psi("some avg10=12.00 avg60=0 avg300=0 total=1\nfull avg10=0.00 avg60=0 avg300=0 total=0") == "warn"
    assert parse_psi("some avg10=2.00 avg60=0 avg300=0 total=1\nfull avg10=6.00 avg60=0 avg300=0 total=0") == "critical"
    assert parse_psi("some avg10=1.00\nfull avg10=0.00") == "normal"
    assert parse_psi("garbage") is None and parse_psi("some avg10=x\nfull avg10=0") is None
    assert read_mem_pressure("Windows") is None
    assert read_run_queue(0) is None
    rq = read_run_queue(4)
    assert rq is None or rq >= 0.0
