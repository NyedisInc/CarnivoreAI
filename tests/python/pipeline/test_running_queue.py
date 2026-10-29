
from __future__ import annotations

import threading

import pytest

from src.core.pipeline import activity
from src.core.pipeline import contract as C
from src.core.pipeline.engine import Engine
from src.core.pipeline import deliver
from src.core.pipeline.observe import TRIGGER_SCAN, DirtySet
from src.core.pipeline.recent import Area, RecentRuns
from tests.pipeline.test_engine import Counting, Fake, drain, transcript

SESSION = Area(session_uuid="u1", session="fix login", project_id=3, project="carnivore")


def _engine(tmp_path, plugins=None, names=None):
    fake = Fake()
    calls = []
    record = RecentRuns(lambda ids: {c: a for c, a in (names or {}).items() if c in ids}, wall=fake.wall,
                        clock=fake.mono)
    engine = Engine(tmp_path / "state", plugins=[p.plugin for p in plugins or [Counting()]], clock=fake.mono,
                    wall=fake.wall, recent_runs=record, notify=lambda: calls.append(1))
    return fake, engine, calls, record


def test_the_queue_is_capped_in_take_order_with_the_total_and_names_from_the_cache_only(tmp_path):
    fake, engine, _, record = _engine(tmp_path, names={"named": SESSION})
    record.prepare(["named"])
    for i in range(activity.QUEUE_LIMIT + 3):
        engine.mark_dirty(transcript(tmp_path / "c", f"scan-{i:02d}.jsonl", 1), TRIGGER_SCAN)
    fake.advance(1.0)
    engine.mark_dirty(transcript(tmp_path / "c", "named.jsonl", 1))
    engine.mark_dirty(transcript(tmp_path / "c", "abcdef0123456789.jsonl", 1))
    fake.advance(4.0)
    queue = engine.status()["queue"]
    assert queue["total"] == activity.QUEUE_LIMIT + 5
    items = queue["items"]
    assert len(items) == activity.QUEUE_LIMIT
    assert [(i["trigger"], i["session"], i["conversation"]) for i in items[:2]] == [
        ("live", "fix login", None), ("live", None, "abcdef01")]
    assert items[2]["trigger"] == "plugins" and items[2]["scope"] == "machine" and items[2]["conversation"] is None
    assert all(i["plugins"] == [] and i["due_at"] is None and not i["backoff"] for i in items)
    assert items[0]["waited_s"] == pytest.approx(4.0) and items[2]["waited_s"] == pytest.approx(5.0)
    assert items[0]["marked_at"] == pytest.approx(fake.wall() - 4.0)


def test_a_key_held_by_one_plugins_backoff_names_that_plugin_and_when_it_is_due(tmp_path):
    good, bad = Counting("good"), Counting("bad")
    fake, engine, _, _ = _engine(tmp_path, plugins=[good, bad])
    target = transcript(tmp_path / "c", "poison.jsonl", 2)
    bad.fail.add(target.path)
    engine.mark_dirty(target, TRIGGER_SCAN)
    drain(engine)
    [item] = engine.status()["queue"]["items"]
    assert item["plugins"] == ["bad"] and item["backoff"] is True
    assert item["due_at"] == pytest.approx(fake.wall() + 5.0)


def test_running_lists_each_plugin_on_the_key_in_flight_and_the_start_names_the_topic(tmp_path):
    fake = Fake()
    seen = {}
    calls = []
    first, second = Counting("first"), Counting("second")
    holder = {}

    def watching(conn, events):
        fake.advance(0.5)
        seen["status"] = holder["engine"].status()
        seen["calls"] = len(calls)
        return first.on_events(conn, events)

    first.plugin = C.Plugin("first", "first.db", 1, first.migrate, watching, first.carry_over)
    record = RecentRuns(lambda ids: {"live": SESSION}, wall=fake.wall, clock=fake.mono)
    engine = Engine(tmp_path / "state", plugins=[first.plugin, second.plugin], clock=fake.mono, wall=fake.wall,
                    recent_runs=record, notify=lambda: calls.append(1))
    holder["engine"] = engine
    engine.mark_dirty(transcript(tmp_path / "c", "live.jsonl", 2))
    engine.step()
    running = seen["status"]["running"]
    assert [(r["plugin"], r["kind"], r["session"], r["trigger"]) for r in running] == [
        ("first", "delivery", "fix login", "live"), ("second", "delivery", "fix login", "live")]
    assert running[0]["running_s"] == pytest.approx(0.5)
    assert running[0]["started_at"] == pytest.approx(fake.wall() - 0.5)
    assert seen["calls"] == 1
    assert len(calls) >= 2
    assert engine.status()["running"] == []


def test_a_rebuild_in_progress_is_a_running_row(tmp_path):
    fake, engine, _, _ = _engine(tmp_path)
    engine.begin_rebuild("count")
    fake.advance(2.0)
    [row] = engine.status()["running"]
    assert (row["plugin"], row["kind"], row["scope"]) == ("count", "rebuild", "machine")
    assert row["running_s"] == pytest.approx(2.0)
    engine.end_rebuild("count")
    engine.step()
    assert engine.status()["running"] == []


def test_a_status_read_never_waits_on_the_delivery_lock(tmp_path):
    _, engine, _, _ = _engine(tmp_path)
    engine.mark_dirty(transcript(tmp_path / "c", "live.jsonl", 1))
    out = {}
    with engine._deliver_lock:
        reader = threading.Thread(target=lambda: out.setdefault("status", engine.status()))
        reader.start()
        reader.join(5.0)
        assert not reader.is_alive(), "the status read blocked on the delivery lock"
    assert out["status"]["queue"]["total"] == 1


def test_an_off_engine_and_an_idle_one_answer_empty_lists(tmp_path):
    _, engine, _, _ = _engine(tmp_path)
    body = engine.status()
    assert body["running"] == [] and body["queue"] == {"items": [], "total": 0}


def test_the_rest_of_the_batch_in_flight_leads_the_queue_and_the_total_matches_the_lag(tmp_path):
    fake = Fake()
    first = Counting("first")
    holder, seen = {}, {}

    def watching(conn, events):
        engine = holder["engine"]
        if "status" not in seen:
            engine.mark_dirty(transcript(tmp_path / "c", "late0000x.jsonl", 1))
            seen["status"] = engine.status()
        return first.on_events(conn, events)

    first.plugin = C.Plugin("first", "first.db", 1, first.migrate, watching, first.carry_over)
    names = {f"key{i}": Area(session_uuid=f"u{i}", session=f"s{i}", project_id=1, project="p") for i in range(5)}
    record = RecentRuns(lambda ids: {c: a for c, a in names.items() if c in ids}, wall=fake.wall, clock=fake.mono)
    engine = Engine(tmp_path / "state", plugins=[first.plugin], clock=fake.mono, wall=fake.wall, recent_runs=record,
                    notify=lambda: None)
    holder["engine"] = engine
    for i in range(5):
        engine.mark_dirty(transcript(tmp_path / "c", f"key{i}.jsonl", 1))
    fake.advance(5.0)
    engine.step()
    body = seen["status"]
    assert len(body["running"]) == 1
    queue = body["queue"]
    assert [i["session"] or i["conversation"] for i in queue["items"]] == ["s1", "s2", "s3", "s4", "late0000"]
    assert queue["total"] == body["lag"]["files"] - 1 == 5
    after = engine.status()["queue"]
    assert [i["conversation"] for i in after["items"]] == ["late0000"] and after["total"] == 1


def _target(name):
    return deliver.FileTarget(f"/nowhere/{name}.jsonl", name, C.FAMILY_CLAUDE, C.FILE_CONVERSATION)


def test_two_due_bulk_keys_are_listed_in_the_order_take_serves_them():
    fake = Fake()
    dirty = DirtySet(fake.mono, min_interval=5.0)
    dirty.mark_file(_target("a"), TRIGGER_SCAN)
    assert [e.conversation_id for e in dirty.take(8)] == ["a"]
    dirty.mark_file(_target("a"), TRIGGER_SCAN)
    dirty.mark_file(_target("b"), TRIGGER_SCAN)
    fake.advance(6.0)
    listed, total = dirty.queue(8)
    assert total == 2
    assert [w.conversation_id for w in listed] == [e.conversation_id for e in dirty.take(8)] == ["b", "a"]
