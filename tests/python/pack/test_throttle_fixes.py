
import sqlite3

import pytest

from src.core.pack.load import process_tree as pt
from src.core.pack.reserve import attached, session_demote as sd, throttle as th
from src.core.terminal_size import TerminalSizeNegotiator

P = pt.Proc
BG = th.PRIO_DARWIN_BG
OVER, UNDER = (9.0, 7.5, 10), (1.0, 7.5, 10)


class Fleet:

    def __init__(self, procs, starts=None, agents=()):
        self.agents = set(agents)
        self.procs = list(procs)
        self.starts = dict(starts or {p.pid: f"t{p.pid}" for p in procs})
        self.prio, self.calls = {}, []

    def setpriority(self, which, pid, value):
        self.calls.append((pid, value))
        self.prio[pid] = value

    def argv_of(self, pids):
        return {p: ("claude",) for p in pids if p in self.agents}

    def start_of(self, pids):
        return {p: self.starts[p] for p in pids if p in self.starts}


def _throttle(fleet, roots, figures, *, exempt=None, select=None):
    return th.Throttle(measure=lambda: figures[0], roots=lambda: roots, exempt=exempt, ps=lambda: fleet.procs, enabled=True,
                       setpriority=fleet.setpriority, start_of=fleet.start_of, select=select, argv_of=fleet.argv_of)



def _stray_fleet():
    return Fleet([P(10, 1, 0, 0), P(11, 10, 0, 0), P(12, 11, 0, 0)], agents={11})


def _orphan(fleet, pid):
    fleet.procs = [P(p.pid, 1 if p.pid == pid else p.ppid, 0, 0) for p in fleet.procs]


def test_stray_with_the_same_start_time_is_restored_once_and_forgotten():
    fleet, figures = _stray_fleet(), [OVER]
    t = _throttle(fleet, [10], figures)
    assert t.tick() == 1 and fleet.prio[12] == BG and BG not in (fleet.prio.get(10), fleet.prio.get(11))
    _orphan(fleet, 12)
    fleet.calls.clear()
    assert t.tick() == 0 and (12, 0) in fleet.calls and fleet.prio[12] == 0
    fleet.calls.clear()
    t.tick()
    assert fleet.calls == [] and 12 not in t.held_pids()


def test_stray_whose_start_time_changed_is_never_touched():
    fleet, figures = _stray_fleet(), [OVER]
    t = _throttle(fleet, [10], figures)
    t.tick()
    _orphan(fleet, 12)
    fleet.starts[12] = "reused"
    fleet.calls.clear()
    t.tick()
    assert fleet.calls == [] and fleet.prio[12] == BG and 12 not in t.held_pids()


def test_dead_stray_is_forgotten_without_a_call():
    fleet, figures = _stray_fleet(), [OVER]
    t = _throttle(fleet, [10], figures)
    t.tick()
    fleet.procs = [p for p in fleet.procs if p.pid != 12]
    del fleet.starts[12]
    fleet.calls.clear()
    t.tick()
    assert fleet.calls == [] and 12 not in t.held_pids()


def test_stray_is_restored_by_the_hysteresis_clear_too_and_no_start_read_without_a_stray():
    fleet, figures, reads = _stray_fleet(), [OVER], []
    t = _throttle(fleet, [10], figures)
    real = fleet.start_of
    t._start_of = lambda pids: (reads.append(set(pids)), real(pids))[1]
    t.tick()
    assert reads == [{12}]
    reads.clear()
    t.tick()
    assert reads == []
    _orphan(fleet, 12)
    figures[0] = UNDER
    fleet.calls.clear()
    t.clear()
    assert fleet.calls == [(12, 0)]



def _db():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE sessions (id INTEGER PRIMARY KEY, tmux_socket TEXT, tmux_name TEXT, origin TEXT NOT NULL);
        CREATE TABLE swarm_agents (id INTEGER PRIMARY KEY, session_row_id INTEGER, torn_down_at TEXT);
        CREATE TABLE swarm_wakes (agent_id INTEGER, ended_at TEXT);
        CREATE TABLE swarm_remote_bodies (session_row_id INTEGER, torn_down_at TEXT);
    """)
    return conn


def _open(conn):
    class Handle:
        def __getattr__(self, name):
            return getattr(conn, name)

        def close(self):
            pass

    return lambda: Handle()


def _seed(conn):
    conn.executemany("INSERT INTO sessions VALUES (?, ?, ?, ?)", [
        (1, "testsock", "body_one", "created"), (2, "testsock", "body_two", "created"), (3, "testsock", "plain", "created"),
        (4, "peer", "remote_one", "peer"), (5, "peer", "remote_body", "peer")])
    conn.executemany("INSERT INTO swarm_agents VALUES (?, ?, NULL)", [(1, 1), (2, 2)])
    conn.executemany("INSERT INTO swarm_wakes VALUES (?, NULL)", [(1,), (2,)])
    conn.execute("INSERT INTO swarm_remote_bodies VALUES (5, NULL)")


@pytest.fixture()
def tmux(monkeypatch):
    asked = []

    def prefix(socket):
        asked.append(socket)
        return ["tmux", "-L", socket]

    monkeypatch.setattr(sd, "tmux_argv_prefix", prefix)
    monkeypatch.setattr(th, "tmux_argv_prefix", prefix)
    return asked


def test_peer_rows_never_cause_a_tmux_call_in_either_throttle_path(tmux):
    conn = _db()
    _seed(conn)
    ran = []

    def run(argv):
        ran.append(argv)
        extra = "\t0" if "attached" in argv[-1] else ""
        return "".join(f"{n}\t{p}{extra}\n" for n, p in (("body_one", 101), ("body_two", 102), ("plain", 103)))

    panes = sd.pane_roots(_open(conn), run=run)
    assert panes == {"plain": [103]}
    loose, held = th.agent_panes(_open(conn), run=run)
    assert sorted(loose + held) == [101, 102]
    assert {a[2] for a in ran} == {"testsock"} and set(tmux) == {"testsock"}



def _bodies(run_lines):
    conn = _db()
    conn.executemany("INSERT INTO sessions VALUES (?, 'testsock', ?, 'created')", [(i, n) for i, n in enumerate(("tmuxed", "watched", "typed", "plain", "hidden"), 1)])
    conn.executemany("INSERT INTO swarm_agents VALUES (?, ?, NULL)", [(i, i) for i in range(1, 6)])
    conn.executemany("INSERT INTO swarm_wakes VALUES (?, NULL)", [(i,) for i in range(1, 6)])
    return conn, lambda argv: run_lines


LINES = "tmuxed\t11\t1\nwatched\t21\t0\ntyped\t31\t0\nplain\t41\t0\nhidden\t51\t0\n"


def test_agent_panes_splits_attached_from_loose(tmux):
    conn, run = _bodies(LINES)
    loose, held = th.agent_panes(_open(conn), run=run, viewing=lambda names: {"watched", "typed"} & names)
    assert sorted(loose) == [41, 51] and sorted(held) == [11, 21, 31]


class _Registry:
    def __init__(self, ids):
        self.ids = ids

    def registered_ids_for_tmux_name(self, name):
        return self.ids.get(name, [])


class _Manager:
    def __init__(self, ids):
        self._registry = _Registry(ids)
        self._terminal_size_negotiator = TerminalSizeNegotiator()


def test_viewing_counts_a_visible_terminal_viewer_and_recent_input_but_not_a_hidden_tab():
    mgr = _Manager({"watched": ["ses_w"], "hidden": ["ses_h"], "typed": ["ses_t"], "plain": ["ses_p"]})
    neg = mgr._terminal_size_negotiator
    neg.set_client_size("ses_w", "ws1", 80, 24, voting=True)
    neg.set_client_size("ses_h", "ws2", 80, 24, voting=False)
    sd.note_viewer_input("typed")
    try:
        got = attached.make_viewing(lambda: mgr)({"watched", "hidden", "typed", "plain"})
    finally:
        sd._last_input.pop("typed", None)
    assert got == {"watched", "typed"}
    assert attached.make_viewing(lambda: None)({"watched"}) == set()


def _fleet_of_bodies():
    procs = []
    for root in (11, 21, 31, 41, 51):
        procs += [P(root, 1, 0, 0), P(root + 1, root, 0, 0), P(root + 2, root + 1, 0, 0)]
    return Fleet(procs, agents={root + 1 for root in (11, 21, 31, 41, 51)})


def test_attached_bodies_are_not_demoted_and_earlier_demotions_come_back_within_one_tick(tmux):
    conn, run = _bodies(LINES)
    fleet = _fleet_of_bodies()
    for pid in (11, 12, 13, 21, 22, 23, 31, 32, 33):
        fleet.prio[pid] = BG
    box = attached.BodyPanes(_open(conn), run=run, viewing=lambda names: {"watched", "typed"} & names)
    t = _throttle(fleet, [], [OVER], exempt=box.attached)
    t._roots = box.loose
    assert t.held_pids() == frozenset()
    t.tick()
    assert {fleet.prio.get(p) for p in (11, 12, 13, 21, 22, 23, 31, 32, 33)} == {0}
    assert {fleet.prio[p] for p in (43, 53)} == {BG}
    assert fleet.prio.get(42, 0) == 0 and fleet.prio.get(52, 0) == 0
    fleet.calls.clear()
    t.tick()
    assert fleet.calls == []


def test_a_body_that_becomes_attached_is_restored_on_the_next_beat(tmux):
    conn, run = _bodies(LINES)
    fleet, watching = _fleet_of_bodies(), [set()]
    box = attached.BodyPanes(_open(conn), run=run, viewing=lambda names: watching[0] & names)
    t = _throttle(fleet, [], [OVER], exempt=box.attached)
    t._roots = box.loose
    t.tick()
    assert fleet.prio[43] == BG and fleet.prio.get(42, 0) == 0
    watching[0] = {"plain"}
    t.tick()
    assert fleet.prio[43] == 0 and 43 not in t.held_pids()


@pytest.mark.parametrize("figures", [(7.2, 7.5, 10), (1.0, 7.5, 10)], ids=["inside_the_band", "fully_under_the_line"])
def test_a_body_that_becomes_attached_is_restored_even_when_the_machine_is_no_longer_over_the_line(tmux, figures):
    conn, run = _bodies(LINES)
    fleet, watching, load = _fleet_of_bodies(), [set()], [OVER]
    box = attached.BodyPanes(_open(conn), run=run, viewing=lambda names: watching[0] & names)
    t = th.Throttle(measure=lambda: load[0], roots=box.loose, exempt=box.attached, ps=lambda: fleet.procs, enabled=True,
                    setpriority=fleet.setpriority, start_of=fleet.start_of, argv_of=fleet.argv_of)
    t.tick()
    assert fleet.prio[43] == BG
    load[0] = figures
    watching[0] = {"plain"}
    t.tick()
    assert fleet.prio[43] == 0 and 43 not in t.held_pids()
    assert fleet.prio[53] == BG and 53 in t.held_pids()


def test_boot_clear_restores_every_agent_tree_whatever_the_line_says():
    fleet = _fleet_of_bodies()
    for p in fleet.procs:
        fleet.prio[p.pid] = BG
    t = _throttle(fleet, [41], [OVER], exempt=lambda: [11])
    assert t.boot_clear() == 6 and {fleet.prio[p] for p in (11, 12, 13, 41, 42, 43)} == {0}
    assert fleet.prio[21] == BG


def test_the_agent_process_is_never_lowered_only_its_descendants():
    fleet = Fleet([P(10, 1, 0, 0), P(11, 10, 0, 0), P(12, 11, 0, 0), P(13, 12, 0, 0)], agents={11})
    fleet.prio[11] = BG
    t = _throttle(fleet, [10], [OVER])
    assert t.tick() == 2
    assert fleet.prio[12] == BG and fleet.prio[13] == BG and fleet.prio[11] == 0 and fleet.prio.get(10, 0) == 0
    assert (11, BG) not in fleet.calls and (10, BG) not in fleet.calls


def test_a_pane_with_no_agent_process_has_everything_below_its_root_lowered():
    fleet = Fleet([P(10, 1, 0, 0), P(11, 10, 0, 0), P(12, 11, 0, 0)])
    t = _throttle(fleet, [10], [OVER])
    assert t.tick() == 2 and fleet.prio[11] == BG and fleet.prio[12] == BG and fleet.prio.get(10, 0) == 0
