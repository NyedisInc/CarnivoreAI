
from __future__ import annotations

import asyncio
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing

import pytest

from src.core.byoai.contracts import DecideResult, NotConfigured
from src.core.pack.machines import settings_doc
from src.core.pack.machines.roster import PeerInfo, Roster
from src.core.pack.placement import enhanced, explain, queue as spawn_queue
from src.core.pack.placement.ddl import apply_pack_placement
from src.core.pack.placement.workload import resolve
from src.core.pack.reserve import throttle
from src.core.swarm import admission

A, B, C = "install-a", "install-b", "install-c"


def snap(label, *, load1, cores=10, reserve=("away", 10, 10), battery=False, tools=None, mem_total=16.0, mem_avail=12.0):
    level, cpu, mem = reserve
    return {"install_id": label, "label": label, "specs": {"cores": cores},
            "load": {"cores": cores, "load_1": load1, "mem_total_gb": mem_total, "mem_available_gb": mem_avail, "disk_free_gb": 200.0},
            "battery": {"present": True, "on_battery": battery} if battery is not None else None,
            "toolchain": tools if tools is not None else {"playwright": True, "python3.12": True},
            "reserve": {"level": level, "cpu_pct": cpu, "mem_pct": mem}, "restrictions": {}}


class FakeRuntime:
    install_id, label = A, "mac"

    def __init__(self, settings):
        self.roster, self._settings, self.own = Roster(), settings, None

    def settings(self):
        return self._settings

    def own_snapshot(self):
        return self.own


class FakeWired:

    def __init__(self, tmp_path, *, a, b, c=None, **settings):
        self.db = str(tmp_path / "p.db")
        with closing(sqlite3.connect(self.db)) as conn:
            apply_pack_placement(conn)
            conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, display_name TEXT, root TEXT)")
            conn.commit()
        self.runtime = FakeRuntime(settings_doc.PackSettings(master_install_id=A, rev=(0, A), **settings))
        self.set(a=a, b=b, c=c)

    def set(self, *, a, b, c=None):
        self.runtime.own = {**a, "install_id": A}
        self.runtime.roster.record(B, label="studio", snapshot={**b, "install_id": B}, holds_master=A)
        if c is not None:
            self.runtime.roster.record(C, label="third", snapshot={**c, "install_id": C}, holds_master=A)

    def open_db(self):
        return sqlite3.connect(self.db)

    def peers(self):
        return [PeerInfo(i, l, "host", "connected", ["pack.machine"]) for i, l in ((B, "studio"), (C, "third")) if i in self.runtime.roster.entries]


def run(wired, kind=None, *, task_type=None, needs=(), machine=None, record=False, **kw):
    work = resolve({"kind": kind} if kind else None, task_type)
    return asyncio.run(explain.place(explain.Request(work, needs=list(needs), machine=machine), wired=wired, remote=True,
                                     record_it=record, **kw))


def test_browser_job_goes_to_the_machine_with_headroom_after_its_reserve(tmp_path):
    wired = FakeWired(tmp_path, a=snap("a", load1=9.0, reserve=("in_use", 30, 20)), b=snap("b", load1=1.0))
    got = run(wired, "browser")
    assert got.chosen == B and got.mode == "stats"
    assert "studio: 8.0 cores" in got.reason and "10% away reserve" in got.reason
    assert "mac (this computer): 0.0 cores" in got.reason and "30% in use reserve" in got.reason
    mac = next(r for r in got.candidates if r["install_id"] == A)
    assert mac["candidate"] is False and "cores free after its reserve" in mac["filter"]


def test_light_job_stays_home_and_auto_distribute_is_the_control(tmp_path):
    wired = FakeWired(tmp_path, a=snap("a", load1=2.0, reserve=("in_use", 30, 20)), b=snap("b", load1=0.5))
    got = run(wired, "light")
    assert got.chosen == A and got.stayed_home and "light work stays on its home" in got.reason
    with closing(wired.open_db()) as conn:
        conn.execute("ALTER TABLE projects ADD COLUMN uid TEXT")
        conn.execute("ALTER TABLE projects ADD COLUMN home_install_id TEXT")
        conn.execute("INSERT INTO projects (display_name, root, uid, home_install_id) VALUES ('trader', '/p/t', 'u1', ?)", (B,))
        conn.commit()
    away = asyncio.run(explain.place(explain.Request(resolve(None, None), project="trader"), wired=wired, remote=True, record_it=False))
    assert away.chosen == B
    wired.runtime._settings = settings_doc.PackSettings(master_install_id=A, rev=(1, A), auto_distribute=True)
    assert run(wired, "light").chosen == B


def test_battery_blocks_heavy_work_and_not_light(tmp_path):
    wired = FakeWired(tmp_path, a=snap("a", load1=0.5, battery=True), b=snap("b", load1=6.0, reserve=("in_use", 30, 20)))
    assert run(wired, "browser").chosen is None
    got = run(wired, "build")
    assert got.chosen is None and "on battery" in got.reason
    assert run(wired, "light").chosen == A
    wired.set(a=snap("a", load1=0.5, battery=True), b=snap("b", load1=1.0))
    assert run(wired, "browser").chosen == B


def test_high_reserve_on_a_sends_heavy_work_to_b(tmp_path):
    wired = FakeWired(tmp_path, a=snap("a", load1=1.0, reserve=("away", 10, 10)), b=snap("b", load1=3.0, reserve=("away", 10, 10)))
    assert run(wired, "suite").chosen == A
    wired.set(a=snap("a", load1=1.0, reserve=("in_use", 60, 20)), b=snap("b", load1=3.0, reserve=("away", 10, 10)))
    got = run(wired, "suite")
    assert got.chosen == B and "60% in use reserve" in got.reason


def test_a_machine_missing_a_needed_tool_is_never_a_candidate(tmp_path):
    wired = FakeWired(tmp_path, a=snap("a", load1=9.0, reserve=("in_use", 30, 20), tools={"playwright": True}),
                      b=snap("b", load1=0.2, tools={"playwright": False}))
    got = run(wired, "browser", needs=["playwright"])
    assert got.chosen is None
    assert any(r["filter"] == "it lacks playwright" for r in got.candidates)


def test_restriction_of_the_target_is_a_filter(tmp_path):
    b = snap("b", load1=0.2)
    b["restrictions"] = {"may_host_agents": False}
    wired = FakeWired(tmp_path, a=snap("a", load1=9.0, reserve=("in_use", 30, 20)), b=b)
    assert run(wired, "browser").chosen is None


def test_model_path_picks_among_candidates_and_falls_back_at_3_s(tmp_path):
    asked = {}

    async def picks_b(ref, *, state, questions):
        asked["options"] = questions["machine"]["options"]
        asked["state"] = state
        return DecideResult({"machine": {"value": "studio"}})

    async def slow(ref, *, state, questions):
        await asyncio.sleep(30)

    async def outside(ref, *, state, questions):
        return DecideResult({"machine": {"value": "evil"}})

    async def unset(ref, *, state, questions):
        raise NotConfigured("no model")

    c = snap("c", load1=0.1, battery=True)
    wired = FakeWired(tmp_path, a=snap("a", load1=1.0), b=snap("b", load1=2.0), c=c, placement_mode="enhanced")
    assert run(wired, "suite").chosen == A
    got = run(wired, "suite", decide=picks_b, ref="pack.placement")
    assert got.mode == "enhanced" and got.chosen == B
    assert sorted(asked["options"]) == ["mac", "studio"] and "third" not in str(asked["state"])
    assert enhanced.TIMEOUT_SECONDS == 3.0
    started = time.monotonic()
    got = run(wired, "suite", decide=slow, ref="pack.placement")
    took = time.monotonic() - started
    assert got.mode == "fallback" and got.chosen == A and 2.9 <= took < 6.0
    assert got.reason.startswith("model did not answer in 3 s; stats rule:")
    for failing in (outside, unset):
        got = run(wired, "suite", decide=failing, ref="pack.placement")
        assert got.mode == "fallback" and got.chosen == A
    assert run(wired, "light", decide=picks_b, ref="pack.placement").mode == "stats"


def test_every_placement_records_machine_and_reason_and_the_queue_keeps_what_no_machine_takes(tmp_path):
    wired = FakeWired(tmp_path, a=snap("a", load1=9.0, reserve=("in_use", 30, 20)), b=snap("b", load1=0.5))
    got = run(wired, "browser", record=True)
    with closing(wired.open_db()) as conn:
        row = conn.execute("SELECT chosen_install_id, mode, reason FROM pack_placements").fetchone()
        assert row[0] == B and row[1] == "stats" and "studio: 8.5 cores" in row[2]
        qid = spawn_queue.enqueue(conn, {"parent_id": 1, "args": {"job": "j"}}, "no machine")
        assert [r["id"] for r in spawn_queue.list_queue(conn)] == [qid]
        assert spawn_queue.expire_old(conn) == [] and len(spawn_queue.expire_old(conn, now=time.time() + 4000)) == 1
        assert spawn_queue.list_queue(conn) == [] and spawn_queue.cancel(conn, qid) is False
    explicit = run(wired, "browser", machine="mac")
    assert explicit.mode == "explicit" and explicit.chosen == A


def test_admission_refuses_new_work_past_the_reserve_line_and_names_it():
    busy = admission.Machine(8.0, 8.0, 10, 50.0, 16.0)
    said = admission.refusal(busy, 4, reserve=admission.Reserve(30, 20, "in_use"), est_cpu_cores=0.5, est_ram_gb=0.6)
    assert said and said.startswith(admission.PEGGED) and "30% in use reserve" in said
    assert admission.refusal(busy, 4, reserve=admission.Reserve(10, 10, "away")) is None
    assert admission.refusal(busy, 4) is None
    assert admission.refusal(admission.Machine(None, None, None, None), 0, reserve=admission.Reserve(30, 20, "in_use")) is None


def _pri(pid: int) -> int:
    return int(subprocess.run(["ps", "-o", "pri=", "-p", str(pid)], capture_output=True, text=True, check=True).stdout.strip())


@pytest.mark.skipif(sys.platform != "darwin", reason="the background policy is Darwin's")
def test_throttle_puts_only_an_agent_tree_in_the_background_policy_and_clears_it():
    agent = subprocess.Popen(["sleep", "120"], start_new_session=True)
    other = subprocess.Popen(["sleep", "120"], start_new_session=True)
    try:
        time.sleep(0.3)
        before, other_before = _pri(agent.pid), _pri(other.pid)
        now = [0.0]
        figures = [(9.0, 7.0, 10)]
        t = throttle.Throttle(measure=lambda: figures[0], roots=lambda: [agent.pid, os.getpid()], clock=lambda: now[0])
        assert t.tick() == 1
        assert _pri(agent.pid) <= 4 < before
        assert _pri(other.pid) == other_before
        figures[0] = (1.0, 7.0, 10)
        now[0] = 30.0
        assert t.tick() == 1 and _pri(agent.pid) <= 4
        now[0] = 100.0
        assert t.tick() == 0
        assert _pri(agent.pid) > 4
    finally:
        for proc in (agent, other):
            proc.kill()
            proc.wait()


def test_throttle_never_calls_setpriority_on_the_server_or_when_unmeasured():
    calls = []
    t = throttle.Throttle(measure=lambda: (9.0, 7.0, 10), roots=lambda: [os.getpid()], enabled=True,
                          ps=lambda: [throttle.process_tree.Proc(os.getpid(), 1, 0.0, 1)], setpriority=lambda *a: calls.append(a))
    assert t.tick() == 0 and calls == []
    quiet = throttle.Throttle(measure=lambda: None, roots=lambda: [123], enabled=True, setpriority=lambda *a: calls.append(a))
    assert quiet.tick() == 0 and calls == []


def test_agent_pane_pids_includes_a_remote_body_hosted_here(monkeypatch):
    import sqlite3
    monkeypatch.setattr(throttle, "tmux_argv_prefix", lambda socket: ["/picked/tmux", "-L", socket])
    db = sqlite3.connect(":memory:")
    db.executescript("""CREATE TABLE sessions (id INTEGER PRIMARY KEY, tmux_socket TEXT, tmux_name TEXT);
        CREATE TABLE swarm_agents (id INTEGER PRIMARY KEY, session_row_id INTEGER, torn_down_at TEXT);
        CREATE TABLE swarm_wakes (id INTEGER PRIMARY KEY, agent_id INTEGER, ended_at TEXT);
        CREATE TABLE swarm_remote_bodies (session_row_id INTEGER PRIMARY KEY, torn_down_at TEXT);
        INSERT INTO sessions VALUES (1, 'cloude', 'remote_body'), (2, 'cloude', 'gone_body');
        INSERT INTO swarm_remote_bodies VALUES (1, NULL), (2, '2026-10-11T00:00:00Z');""")
    out = "remote_body\t4242\t0\ngone_body\t4343\t0\n"
    seen = []
    assert throttle.agent_pane_pids(lambda: db, run=lambda argv: seen.append(argv) or out) == [4242]
    assert seen[0][:3] == ["/picked/tmux", "-L", "cloude"], "the Pack read uses the version-matching picker"
