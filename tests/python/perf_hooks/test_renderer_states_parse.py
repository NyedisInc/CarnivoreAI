import importlib.util
import pathlib

_SPEC = importlib.util.spec_from_file_location(
    "renderer_states", pathlib.Path(__file__).resolve().parents[3] / "scripts" / "perf" / "renderer_states.py")
rs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rs)

TOP = """Processes: 900 total, 5 running
Load Avg: 5.50, 6.10, 7.20

PID    COMMAND          %CPU IDLEW POWER
70789  Electron Helper  48.6 120   48.6
Processes: 900 total, 5 running

PID    COMMAND          %CPU IDLEW POWER
70789  Electron Helper  4.0  10    4.0
Processes: 900 total, 5 running

PID    COMMAND          %CPU IDLEW POWER
70789  Electron Helper  6.0  20    6.5
"""


def test_parse_top_one_row_per_sample():
    rows = rs.parse_top(TOP)
    assert [r["cpu"] for r in rows] == [48.6, 4.0, 6.0]
    assert rows[0]["pid"] == 70789 and rows[0]["command"] == "Electron Helper"
    assert rows[2]["idlew"] == 20 and rows[2]["power"] == 6.5


def test_summarize_discards_first_sample():
    s = rs.summarize(rs.parse_top(TOP))
    assert s["n"] == 2
    assert s["cpu"] == {"mean": 5.0, "min": 4.0, "max": 6.0}
    assert s["idlew"]["mean"] == 15.0
    assert rs.summarize(rs.parse_top(TOP)[:1]) is None


def test_stream_growth_counts_only_growing_files():
    before = {"a.pipe": 100, "b.pipe": 500, "c.pipe": 900}
    after = {"a.pipe": 1100, "b.pipe": 500, "c.pipe": 10, "d.pipe": 70}
    count, rates = rs.stream_growth(before, after, 10.0)
    assert count == 1 and rates == {"a.pipe": 100.0}


TOP_DELTA = """PID    COMMAND          %CPU IDLEW  POWER
181    WindowServer     0.0  89500  0.0
181    WindowServer     41.6 89506+ 41.8
181    WindowServer     43.4 89519- 44.0
"""


def test_parse_top_keeps_rows_whose_counters_carry_a_delta_suffix():
    rows = rs.parse_top(TOP_DELTA)
    assert [r["cpu"] for r in rows] == [0.0, 41.6, 43.4]
    assert [r["idlew"] for r in rows] == [89500, 89506, 89519]
    assert rows[1]["power"] == 41.8 and rows[1]["command"] == "WindowServer"
