
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from contextlib import closing

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import pipeline_plugin_routes
from src.api.auth import require_auth
from src.core.pipeline import contract as C
from src.core.pipeline import engine as engine_module
from src.core.pipeline import recent, runtime
from src.core.pipeline.deliver import SKIP_TIMEOUT
from src.core.pipeline.engine import Engine
from src.core.pipeline.recent import Area, RecentRuns
from src.core.resource_push import topics
from tests.pipeline.test_engine import Counting, Fake, drain, transcript
from tests.s7_helpers import migrated_connection

SESSION = Area(session_uuid="u1", session="fix login", project_id=3, project="carnivore")


def _engine(tmp_path, plugin=None, names=None, **kw):
    fake, plugin = Fake(), plugin or Counting()
    calls = []
    record = RecentRuns(lambda ids: {c: a for c, a in (names or {}).items() if c in ids}, wall=fake.wall,
                        clock=fake.mono)
    engine = Engine(tmp_path / "state", plugins=[plugin.plugin], clock=fake.mono, wall=fake.wall,
                    recent_runs=record, notify=lambda: calls.append(1), **kw)
    return fake, plugin, engine, calls


def test_rows_are_keyed_by_area_and_plugin_and_updated_in_place():
    r = RecentRuns(lambda ids: {"c1": SESSION, "c2": SESSION, "p1": Area(project_id=3, project="carnivore")})
    r.prepare(["c1", "c2", "p1", "old"])
    for conv in ("c1", "c1", "c2"):
        r.record(plugin_id="stats", conversation_id=conv, family="claude", trigger="live", duration_s=0.01,
                 outcome=recent.OUTCOME_OK, events=1)
    r.record(plugin_id="deepsearch", conversation_id="c1", family="claude", trigger="live", duration_s=0.02,
             outcome=recent.OUTCOME_OK, events=2)
    r.record(plugin_id="stats", conversation_id="p1", family="claude", trigger="plugins", duration_s=0.0,
             outcome=recent.OUTCOME_OK)
    r.record(plugin_id="stats", conversation_id="old", family="claude", trigger="plugins", duration_s=0.0,
             outcome=recent.OUTCOME_OK)
    rows = r.rows()
    assert [(x["plugin"], x["scope"], x["runs"]) for x in rows] == [
        ("stats", "machine", 1), ("stats", "project", 1), ("deepsearch", "session", 1), ("stats", "session", 3)]
    session_row = rows[-1]
    assert session_row["session"] == "fix login" and session_row["project"] == "carnivore"
    assert session_row["conversation_id"] == "c2" and session_row["kind"] == "delivery"
    assert rows[0]["session"] is None and rows[0]["project"] is None
    with pytest.raises(ValueError):
        r.record(plugin_id="stats", conversation_id="c1", family="claude", trigger="live", duration_s=0,
                 outcome="exploded")


def test_the_record_is_bounded_and_drops_the_least_recently_updated_row():
    r = RecentRuns(lambda ids: {c: Area(session_uuid=c) for c in ids}, limit=3)
    r.prepare(["a", "b", "c", "d"])
    for conv in ("a", "b", "c"):
        r.record(plugin_id="stats", conversation_id=conv, family="claude", trigger="live", duration_s=0,
                 outcome=recent.OUTCOME_OK)
    r.record(plugin_id="stats", conversation_id="a", family="claude", trigger="live", duration_s=0,
             outcome=recent.OUTCOME_OK)
    r.record(plugin_id="stats", conversation_id="d", family="claude", trigger="live", duration_s=0,
             outcome=recent.OUTCOME_OK)
    assert [x["session_uuid"] for x in r.rows()] == ["d", "a", "c"]


def test_names_are_resolved_once_per_batch_and_cached():
    asked = []
    clock = Fake()

    def resolve(ids):
        asked.append(tuple(ids))
        return {c: SESSION for c in ids}

    r = RecentRuns(resolve, clock=clock.mono, name_ttl=60.0)
    r.prepare(["c1", "c2", "c1"])
    for _ in range(5):
        r.record(plugin_id="stats", conversation_id="c1", family="claude", trigger="live", duration_s=0,
                 outcome=recent.OUTCOME_OK)
    assert asked == [("c1", "c2")]
    clock.advance(61.0)
    r.record(plugin_id="stats", conversation_id="c1", family="claude", trigger="live", duration_s=0,
             outcome=recent.OUTCOME_OK)
    assert asked == [("c1", "c2")]
    assert r.rows()[0]["scope"] == "machine"
    r.prepare(["c1"])
    assert asked[-1] == ("c1",)


def test_a_miss_is_retried_after_the_short_negative_ttl():
    clock = Fake()
    answers = [{}]

    def resolve(ids):
        return answers[-1]

    r = RecentRuns(resolve, clock=clock.mono, name_ttl=60.0, negative_ttl=5.0)
    r.prepare(["new"])
    assert r.cached_area("new") is recent.MACHINE
    answers.append({"new": SESSION})
    clock.advance(3.0)
    r.prepare(["new"])
    assert r.cached_area("new") is recent.MACHINE
    clock.advance(3.0)
    r.prepare(["new"])
    assert r.cached_area("new") == SESSION


def test_many_threads_recording_lose_no_run():
    r = RecentRuns(lambda ids: {c: Area(session_uuid=c) for c in ids})
    r.prepare([f"s{n}" for n in range(20)])
    start = threading.Barrier(8)

    def work(n):
        start.wait()
        for i in range(500):
            r.record(plugin_id="stats", conversation_id=f"s{(n + i) % 20}", family="claude", trigger="live",
                     duration_s=0.001, outcome=recent.OUTCOME_OK, events=1)
            r.rows()

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    rows = r.rows()
    assert len(rows) == 20 and sum(x["runs"] for x in rows) == 8 * 500


def test_the_engine_times_each_plugin_on_the_monotonic_clock_and_records_ok(tmp_path):
    fake = Fake()
    plugin = Counting()
    real = plugin.on_events

    def slow(conn, events):
        fake.advance(0.25)
        return real(conn, events)

    plugin.plugin = C.Plugin("count", "count.db", 1, plugin.migrate, slow, plugin.carry_over)
    calls = []
    record = RecentRuns(lambda ids: {c: SESSION for c in ids}, wall=fake.wall, clock=fake.mono)
    engine = Engine(tmp_path / "state", plugins=[plugin.plugin], clock=fake.mono, wall=fake.wall,
                    recent_runs=record, notify=lambda: calls.append(1))
    target = transcript(tmp_path / "c", "live.jsonl", 3)
    engine.mark_dirty(target)
    drain(engine)
    [row] = engine.status()["recent"]
    assert row["plugin"] == "count" and row["outcome"] == "ok" and row["runs"] == 1 and row["events"] == 1
    assert row["duration_ms"] == pytest.approx(250.0) and row["session"] == "fix login"
    assert row["trigger"] == "live" and row["finished_at"] == pytest.approx(fake.wall())
    assert calls
    fake.advance(3.0)
    engine.mark_dirty(target)
    drain(engine)
    assert engine.status()["recent"][0]["runs"] == 1


def test_each_plugin_keeps_its_last_delivery_and_runs_when_its_chart_row_reads_failed(tmp_path):
    fake, plugin, engine, _ = _engine(tmp_path, names={"good": SESSION, "poison": SESSION})
    assert engine.status()["plugins"]["count"]["last_delivery_at"] is None
    assert engine.status()["plugins"]["count"]["runs"] == 0
    engine.mark_dirty(transcript(tmp_path / "c", "good.jsonl", 2))
    drain(engine)
    delivered_at = fake.wall()
    fake.advance(300.0)
    poison = transcript(tmp_path / "c", "poison.jsonl", 2)
    plugin.fail.add(poison.path)
    engine.mark_dirty(poison)
    drain(engine)
    body = engine.status()
    [row] = body["recent"]
    assert row["outcome"] == "failed"
    assert body["plugins"]["count"]["last_delivery_at"] == pytest.approx(delivered_at)
    assert body["plugins"]["count"]["runs"] == 2


def test_a_plugin_failure_is_failed_and_an_unreadable_file_is_parked(tmp_path, monkeypatch):
    _, plugin, engine, _ = _engine(tmp_path, names={})
    poison = transcript(tmp_path / "c", "poison.jsonl", 2)
    plugin.fail.add(poison.path)
    engine.mark_dirty(poison)
    drain(engine)
    [row] = engine.status()["recent"]
    assert (row["outcome"], row["error"], row["scope"]) == ("failed", "RuntimeError", "machine")
    _, _, parked, _ = _engine(tmp_path / "second", names={})
    monkeypatch.setattr(engine_module, "deliver_file", lambda delivery, target: delivery.skip(SKIP_TIMEOUT))
    parked.mark_dirty(transcript(tmp_path / "d", "hung.jsonl", 2))
    parked.mark_dirty(transcript(tmp_path / "d", "hung2.jsonl", 2))
    drain(parked)
    [row] = parked.status()["recent"]
    assert (row["outcome"], row["error"], row["runs"]) == ("parked", "timeout", 2)


def test_pause_resume_and_a_rebuild_name_the_topic_and_the_rebuild_is_a_machine_row(tmp_path):
    fake, plugin, engine, calls = _engine(tmp_path)
    engine.pause("count")
    engine.resume("count")
    assert len(calls) == 2
    engine.begin_rebuild("count")
    fake.advance(1.5)
    engine.end_rebuild("count")
    [row] = engine.status()["recent"]
    assert (row["kind"], row["scope"], row["outcome"], row["trigger"]) == ("rebuild", "machine", "ok", "rebuild")
    assert row["duration_ms"] == pytest.approx(1500.0)
    assert len(calls) >= 4
    result = engine.rebuild_plugin("count")
    assert result["files_marked"] == 0 and engine.status()["recent"][0]["runs"] == 2


def test_a_failed_rebuild_is_recorded_failed(tmp_path, monkeypatch):
    from src.core.pipeline import plugin_db
    from src.core.pipeline import rebuild as rebuild_module

    def broken(engine, plugin):
        raise plugin_db.PluginUnavailable("disk said no")

    _, _, engine, _ = _engine(tmp_path)
    monkeypatch.setattr(rebuild_module, "_swap", broken)
    with pytest.raises(plugin_db.PluginUnavailable):
        engine.rebuild_plugin("count")
    [row] = engine.status()["recent"]
    assert (row["kind"], row["outcome"], row["error"]) == ("rebuild", "failed", "PluginUnavailable")


def test_the_default_notify_names_the_pipeline_topic_coalesced(monkeypatch):
    from src.core import resource_push

    seen = []
    monkeypatch.setattr(resource_push, "notify_coalesced", lambda *a: seen.append(a))
    engine_module.push_status()
    assert seen == [(topics.PIPELINE, engine_module.PUSH_KEY, engine_module.PUSH_INTERVAL_SECONDS)]
    assert topics.PIPELINE in topics.RESOURCE_TOPICS


def test_names_come_from_the_main_database(tmp_path):
    from src.core.db import db_path_for

    state = tmp_path / "state"
    state.mkdir()
    migrated_connection(state).close()
    db = db_path_for(state)
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, working_dir, origin, "
                     "lifecycle, claude_session_uuid, agent_type, agent_family, created_at, updated_at, title) VALUES "
                     "('sess-1','cloude','cloude_a',1,'/w','created','stopped','conv-1','claude','claude','t','t',"
                     "'fix login')")
        conn.commit()
    found = recent.db_resolver(db)(["conv-1", "conv-unknown"])
    assert found["conv-1"].session == "fix login" and found["conv-1"].scope == "session"
    assert "conv-unknown" not in found
    assert recent.db_resolver(tmp_path / "missing.db")(["conv-1"]) == {}


@pytest.fixture
def running(tmp_path, monkeypatch):
    _, _, engine, _ = _engine(tmp_path, names={"c1": SESSION})
    engine.recent.prepare(["c1"])
    engine.recent.record(plugin_id="stats", conversation_id="c1", family="claude", trigger="live", duration_s=0.012,
                         outcome=recent.OUTCOME_OK, events=4)
    monkeypatch.setattr(runtime, "_engine", engine)
    return engine


ROW_KEYS = {"plugin", "kind", "scope", "session_uuid", "session", "project_id", "project", "conversation_id", "family",
            "trigger", "finished_at", "duration_ms", "runs", "events", "outcome", "error"}


def test_the_status_route_carries_the_recent_rows(running):
    app = FastAPI()
    app.include_router(pipeline_plugin_routes.router)
    app.dependency_overrides[require_auth] = lambda: None
    body = TestClient(app).get("/pipeline/status").json()
    assert body["state"] == "caught_up"
    [row] = body["recent"]
    assert set(row) == ROW_KEYS
    assert (row["plugin"], row["session"], row["duration_ms"], row["outcome"]) == ("stats", "fix login", 12.0, "ok")


def test_the_status_route_needs_auth():
    app = FastAPI()
    app.include_router(pipeline_plugin_routes.router)
    assert TestClient(app).get("/pipeline/status").status_code in (401, 403)


def test_the_mcp_pipeline_status_tool_returns_the_recent_rows(running):
    from src.core.mcp import read_tools
    from src.core.mcp.caller import AgentCaller

    out = asyncio.run(read_tools.pipeline_status(None, AgentCaller("ses_a", "cloude_a", "ses_a"), {}))
    body = json.loads(out["content"][0]["text"])
    assert [r["session"] for r in body["recent"]] == ["fix login"]


def test_a_resolver_that_raises_leaves_the_machine_and_never_costs_the_engine_a_key(tmp_path):
    def broken(ids):
        raise RuntimeError("resolver bug")

    fake, plugin = Fake(), Counting()
    engine = Engine(tmp_path / "state", plugins=[plugin.plugin], clock=fake.mono, wall=fake.wall,
                    recent_runs=RecentRuns(broken, wall=fake.wall, clock=fake.mono), notify=lambda: None)
    target = transcript(tmp_path / "c", "live.jsonl", 3)
    engine.mark_dirty(target)
    assert drain(engine) is None and plugin.counts(engine.state_dir) == {target.path: 3}
    assert engine.status()["recent"][0]["scope"] == "machine"


def test_a_rebuild_replay_is_the_machine_and_keeps_a_live_sessions_row(tmp_path):
    from src.core.pipeline.observe import TRIGGER_REBUILD

    asked = []
    fake, plugin = Fake(), Counting()

    def resolve(ids):
        asked.extend(ids)
        return {c: Area(session_uuid=f"u-{c}", session=c) for c in ids}

    record = RecentRuns(resolve, wall=fake.wall, clock=fake.mono)
    engine = Engine(tmp_path / "state", plugins=[plugin.plugin], clock=fake.mono, wall=fake.wall,
                    recent_runs=record, notify=lambda: None)
    engine.mark_dirty(transcript(tmp_path / "c", "live.jsonl", 2))
    drain(engine)
    for n in range(recent.ROW_LIMIT + 20):
        engine.mark_dirty(transcript(tmp_path / "old", f"old{n}.jsonl", 1), TRIGGER_REBUILD)
    for _ in range(50):
        fake.advance(1.0)
        if drain(engine) is None:
            break
    rows = engine.status()["recent"]
    by_scope = {x["scope"]: x for x in rows}
    assert len(rows) == 2 and by_scope["session"]["session"] == "live" and by_scope["session"]["runs"] == 1
    assert by_scope["machine"]["runs"] == recent.ROW_LIMIT + 20 and by_scope["machine"]["trigger"] == "rebuild"
    assert asked == ["live"]


def test_a_failing_record_never_parks_the_key_or_keeps_a_plugin_paused(tmp_path, monkeypatch):
    fake, plugin, engine, _ = _engine(tmp_path)

    def broken(**kw):
        raise ValueError("record bug")

    monkeypatch.setattr(engine.recent, "record", broken)
    monkeypatch.setattr(engine.recent, "record_rebuild", broken)
    target = transcript(tmp_path / "c", "live.jsonl", 3)
    engine.mark_dirty(target)
    assert drain(engine) is None
    assert plugin.counts(engine.state_dir) == {target.path: 3} and not engine._in_flight
    engine.begin_rebuild("count")
    engine.end_rebuild("count")
    assert "count" not in engine._paused


def test_a_rebuilds_run_time_starts_after_the_pause_waits_out_a_delivery(tmp_path):
    fake, plugin, engine, _ = _engine(tmp_path)
    real_pause = engine.pause

    def slow_pause(plugin_id):
        fake.advance(20.0)
        real_pause(plugin_id)

    engine.pause = slow_pause
    engine.begin_rebuild("count")
    fake.advance(2.0)
    engine.end_rebuild("count")
    [row] = engine.status()["recent"]
    assert row["kind"] == "rebuild" and row["duration_ms"] == pytest.approx(2000.0)


def test_the_name_read_uses_the_index_and_project_names_without_prompt_text(tmp_path):
    with closing(sqlite3.connect(tmp_path / "n.db")) as conn:
        conn.execute("CREATE TABLE conversation_index (conversation_id TEXT, session_uuid TEXT, session_name TEXT, "
                     "project_id INTEGER, project_name TEXT)")
        conn.execute("CREATE TABLE projects (id INTEGER, display_name TEXT)")
        conn.execute("INSERT INTO conversation_index VALUES ('c1', 'u1', 'fix login', 3, NULL)")
        conn.execute("INSERT INTO conversation_index VALUES ('c2', NULL, NULL, 3, 'carnivore')")
        conn.execute("INSERT INTO projects VALUES (3, 'carnivore')")
        found = recent.read_names(conn, ["c1", "c2", "c3"])
    assert found["c1"] == Area("u1", "fix login", 3, "carnivore")
    assert found["c2"].scope == "project" and "c3" not in found
