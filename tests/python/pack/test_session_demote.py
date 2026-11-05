
from src.core.pack.load import process_tree as pt
from src.core.pack.reserve import session_demote as sd
from src.core.pack.reserve import throttle as th

P = pt.Proc
PROCS = [P(10, 1, 0, 0), P(11, 10, 0, 0), P(12, 11, 0, 0), P(13, 12, 0, 0), P(14, 11, 0, 0),
         P(20, 1, 0, 0), P(21, 20, 0, 0), P(22, 21, 0, 0), P(30, 1, 0, 0), P(31, 30, 0, 0), P(99, 1, 0, 0)]
PANES = {"a": [10], "b": [20], "c": [30]}
ARGV = {11: ("claude", "--x"), 21: ("node", "/x/bin/codex"), 12: ("pytest",), 31: ("sleep",)}


def test_selects_only_agent_descendants_of_unfocused_sessions():
    demote, scope = sd.select_demotions(PROCS, PANES, ARGV, focused=set())
    assert demote == {12, 13, 14, 22}
    assert 99 not in scope and {10, 11, 20, 30, 31} <= scope


def test_focused_session_is_exempt_entirely():
    demote, scope = sd.select_demotions(PROCS, PANES, ARGV, focused={"a"})
    assert demote == {22} and {12, 13, 14} <= scope


def test_focus_window_and_agent_names():
    sd.note_viewer_input("a", now=100.0)
    assert sd.focused_sessions(now=150.0) == {"a"} and sd.focused_sessions(now=221.0) == set()
    assert sd.is_agent_argv(("claude",)) and not sd.is_agent_argv(("pytest",)) and not sd.is_agent_argv(())


def _throttle(figures, calls, clock):
    return th.Throttle(measure=lambda: figures[0], roots=lambda: [], ps=lambda: PROCS, enabled=True, clock=clock,
                       setpriority=lambda which, pid, val: calls.append((pid, val)),
                       select=lambda procs: sd.select_demotions(procs, PANES, ARGV, focus[0]))


focus = [set()]


def test_throttle_demotes_over_line_clears_on_focus_and_on_hysteresis_and_never_when_unmeasured():
    now, calls, figures = [0.0], [], [None]
    t = _throttle(figures, calls, lambda: now[0])
    assert t.tick() == 0 and calls == []
    figures[0] = (9.0, 7.5, 10)
    assert t.tick() == 4 and {c for c in calls} == {(p, th.PRIO_DARWIN_BG) for p in (12, 13, 14, 22)}
    calls.clear()
    focus[0] = {"a"}
    assert t.tick() == 1 and sorted(calls) == [(12, 0), (13, 0), (14, 0)]
    calls.clear()
    figures[0] = (1.0, 7.5, 10)
    assert t.tick() == 1 and calls == []
    now[0] = 61.0
    assert t.tick() == 0 and calls == [(22, 0)]
    focus[0] = set()
