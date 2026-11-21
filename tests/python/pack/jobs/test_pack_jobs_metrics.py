
from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from typing import Any, Dict, List

from src.api import pack_jobs_metrics_routes as routes
from src.core.mcp import pack_jobs_metrics_tools as tool
from src.core.pack.jobs import boot, metrics
from src.core.pack.jobs.miss_count import MissCounter
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import JobRecord, JobState
from src.core.pack.load.process_tree import Proc
from src.core.pack.placement import maintain
from src.core.pack.reserve import session_demote

NOW = 1_800_000_000.0
DAY = 86400.0
UID = "p1x23456"
PANES = {"carnivore_a": [10]}
ARGV = {11: ("claude",)}


def procs(cpu: float) -> List[Proc]:
    return [Proc(10, 1, 0.0, 1), Proc(11, 10, 0.0, 1), Proc(12, 11, cpu, 1)]


def counter(store: JobStore, *, recent: bool = False, free: bool = False, marked: bool = True) -> MissCounter:
    return MissCounter(store, sessions_of_marked=lambda: {"carnivore_a": (UID, "uuid-a")} if marked else {},
                       recent_delegate=lambda _s, _w: recent, peer_free=lambda _u: free, clock=iter(range(0, 10_000, 10)).__next__,
                       wall=lambda: NOW)


def beats(c: MissCounter, cpus: List[float], pegged: bool = True) -> None:
    for cpu in cpus:
        c.observe(procs(cpu), PANES, ARGV, pegged)


def outcomes(store: JobStore) -> List[str]:
    return [o for _u, _m, o in store.episodes_since(0)]


def test_session_trees_skips_agent_and_root() -> None:
    assert session_demote.session_trees(procs(50), PANES, ARGV) == {"carnivore_a": {12}}
    assert session_demote.session_trees(procs(50), PANES, {}) == {}


def test_episode_opens_after_three_beats_and_closes_after_two(tmp_path) -> None:
    store = JobStore(tmp_path)
    c = counter(store)
    beats(c, [150, 150])
    beats(c, [10, 10])
    assert outcomes(store) == []
    beats(c, [150, 150, 150, 150])
    beats(c, [10])
    assert outcomes(store) == []
    beats(c, [150, 10, 10])
    assert outcomes(store) == ["local_ok"]
    assert store.episodes_since(0)[0][1] > 0


def test_delegated_miss_and_local_ok_each_counted(tmp_path) -> None:
    store = JobStore(tmp_path)
    for recent, free in ((True, True), (False, True), (False, False)):
        c = counter(store, recent=recent, free=free)
        beats(c, [150, 150, 150, 10, 10])
    assert outcomes(store) == ["delegated", "miss", "local_ok"]


def test_nothing_measured_while_not_pegged_and_pegged_clear_closes(tmp_path) -> None:
    store = JobStore(tmp_path)
    c = counter(store)
    beats(c, [150, 150, 150, 150], pegged=False)
    assert outcomes(store) == []
    beats(c, [150, 150, 150])
    beats(c, [150], pegged=False)
    assert outcomes(store) == ["local_ok"]
    beats(c, [150, 150, 150], pegged=True)
    assert counter(store, marked=False) and outcomes(store) == ["local_ok"]


def test_unmarked_project_is_not_counted(tmp_path) -> None:
    store = JobStore(tmp_path)
    c = counter(store, marked=False)
    beats(c, [150] * 5 + [10, 10])
    assert outcomes(store) == []


def test_stored_row_holds_no_name_or_path(tmp_path) -> None:
    store = JobStore(tmp_path)
    beats(counter(store), [150, 150, 150, 10, 10])
    with sqlite3.connect(tmp_path / "pack-jobs.db") as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(heavy_episodes)")]
        row = conn.execute("SELECT * FROM heavy_episodes").fetchone()
    assert cols == ["id", "day", "project_uid", "minutes", "outcome", "at"]
    text = json.dumps(row)
    assert "carnivore_a" not in text and "claude" not in text and "uuid-a" not in text and "/" not in text.replace("-", "")


def add_job(store: JobStore, jid: str, *, kind: str = "suite", peer: Any = None, started: float = 0, ended: float = 0, at: float = NOW) -> None:
    store.create_job(JobRecord(id=jid, project_uid=UID, request_json=json.dumps({"request": {"kind": kind}}), state=JobState.DONE if peer else JobState.HERE,
                               peer_install_id=peer, created_at=at, updated_at=at, started_at=started or None, ended_at=ended or None))


def test_p3_flag_needs_enough_data(tmp_path) -> None:
    store = JobStore(tmp_path)
    store.policy_upsert(UID, auto_delegate=1)
    for i in range(9):
        store.episode_add("d", UID, 1.0, "miss", NOW - 2 * DAY + i)
    for i in range(3):
        add_job(store, f"job_{i:012d}", at=NOW - DAY)
    p3 = metrics.p3(store, now=NOW)
    assert (p3["misses"], p3["delegate_calls"], p3["share"]) == (9, 3, 0.75)
    assert p3["enough_data"] is False and p3["over"] is False
    for i in range(10):
        store.episode_add("d", UID, 1.0, "local_ok", NOW - 2 * DAY + i)
    assert metrics.p3(store, now=NOW)["enough_data"] is False
    old_hour = int((NOW - 8 * DAY) // 3600)
    store.load_hours_put([{"hour": old_hour, "busy_pct": 1.0, "pegged_minutes": 0.0, "max_run_queue_per_core": None, "mem_warn_minutes": 0.0}],
                         keep_since_hour=old_hour - 1)
    p3 = metrics.p3(store, now=NOW)
    assert p3["enough_data"] is True and p3["over"] is True


def test_p3_counts_only_heavy_kinds_in_marked_projects(tmp_path) -> None:
    store = JobStore(tmp_path)
    add_job(store, "job_000000000001")
    assert metrics.p3(store, now=NOW)["delegate_calls"] == 0
    store.policy_upsert(UID, auto_delegate=1)
    add_job(store, "job_000000000002", kind="light")
    assert metrics.p3(store, now=NOW)["delegate_calls"] == 1


def test_r3_share_from_jobs_and_episodes(tmp_path) -> None:
    store = JobStore(tmp_path)
    assert metrics.r3(store, 7, now=NOW)["share"] is None
    add_job(store, "job_000000000001", peer="iid-b", started=NOW - 3600, ended=NOW - 3600 + 600)
    add_job(store, "job_000000000002", peer="iid-b", started=NOW - 20 * DAY, ended=NOW - 20 * DAY + 600)
    store.episode_add("d", UID, 30.0, "local_ok", NOW - 100)
    r3 = metrics.r3(store, 7, now=NOW)
    assert (r3["remote_minutes"], r3["local_minutes"], r3["share"]) == (10.0, 30.0, 0.25)


class FakeGauge:

    def __init__(self) -> None:
        self.calls = 0

    def pegged(self) -> bool:
        return False

    def hours(self) -> List[Dict[str, Any]]:
        self.calls += 1
        return [{"hour": int(NOW // 3600), "busy_pct": 40.0, "pegged_minutes": 2.0, "max_run_queue_per_core": 1.1, "mem_warn_minutes": 0.0}]


def test_hours_flush_once_a_minute(tmp_path, monkeypatch) -> None:
    store = JobStore(tmp_path)
    monkeypatch.setattr(boot, "engine", lambda: SimpleNamespace(store=store))
    clock = {"t": 0.0}
    gauge = FakeGauge()
    wired = SimpleNamespace(open_db=lambda: sqlite3.connect(":memory:"))
    beat = maintain.MetricsBeat(wired, gauge, clock=lambda: clock["t"], wall=lambda: NOW)
    for t in (0, 10, 20, 59):
        clock["t"] = t
        beat.tick()
    assert gauge.calls == 1
    clock["t"] = 61
    beat.tick()
    assert gauge.calls == 2
    assert metrics.load(store, now=NOW)["hours"] == [{"hour": int(NOW // 3600), "busy_pct": 40.0, "pegged_minutes": 2.0,
                                                    "max_run_queue_per_core": 1.1, "mem_warn_minutes": 0.0}]


def test_report_shape_route_tool_and_order(tmp_path, monkeypatch) -> None:
    store = JobStore(tmp_path)
    monkeypatch.setattr(boot, "engine", lambda: SimpleNamespace(store=store))
    out = routes._report(30)
    assert set(out) == {"days", "p3", "r3", "load"} and out["days"] == 30
    assert set(out["p3"]) == {"window_days", "misses", "local_ok", "delegated", "delegate_calls", "share", "threshold", "over", "enough_data", "since"}
    assert set(out["r3"]) == {"window_days", "remote_minutes", "local_minutes", "share"} and out["load"] == {"hours": []}
    assert metrics.report(store, 99, now=NOW)["days"] == 30
    seen: Dict[str, Any] = {}
    tool.SPECS[0].invoke(SimpleNamespace(route=lambda days: seen.setdefault("days", days), args={"days": 3}))
    assert seen == {"days": 3}
    from src.main import app
    from tests.test_route_auth_inventory import _walk

    paths = [p for kind, p, r, _i in _walk(app.routes) if kind == "http" and "GET" in r.methods]
    assert paths.index("/api/v1/pack/jobs/metrics") < paths.index("/api/v1/pack/jobs/{job_id}")
