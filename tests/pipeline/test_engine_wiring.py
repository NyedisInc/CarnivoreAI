
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.attention.fs_trigger import KQUEUE_AVAILABLE, FsTrigger
from src.core.pipeline import registry, runtime, scan
from src.core.pipeline.engine import THREAD_SCAN, THREAD_WORKER, Engine
from src.core.pipeline.feed import LiveFeed
from src.core.pipeline import triggers, wiring
from src.core.deepsearch import fallback_hook as fb
from tests.pipeline import corpus as K
from tests.s7_helpers import migrated_connection

NEW_THREADS = {THREAD_WORKER, THREAD_SCAN}


def _names() -> set:
    return {t.name for t in threading.enumerate()}


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    from src.core.db import db_path_for
    state = tmp_path / "state"
    state.mkdir()
    migrated_connection(state).close()
    db = db_path_for(state)
    monkeypatch.setattr(triggers, "default_paths", lambda: (state, db))
    monkeypatch.setenv("CARNIVORE_STATE_DIR", str(state))
    monkeypatch.setattr(scan.Scanner, "_walk", lambda self: SimpleNamespace(changed=()))
    yield SimpleNamespace(state=state, db=db)
    runtime.stop()


def test_boot_starts_exactly_the_engines_two_threads_and_stop_ends_them(wired, monkeypatch):
    monkeypatch.delenv("CLOUDE_TEST_MODE", raising=False)
    monkeypatch.delenv("CLOUDE_SAVE_PIPELINE", raising=False)
    assert not (_names() & NEW_THREADS)
    assert fb.booting() is False
    assert wiring.install() is True
    assert fb.booting() is True
    deadline = time.time() + 5
    while not NEW_THREADS <= _names() and time.time() < deadline:
        time.sleep(0.02)
    assert NEW_THREADS <= _names() and len(NEW_THREADS) > 0
    assert not {n for n in _names() if n.startswith("save-pipeline")}
    wiring.uninstall()
    assert not (_names() & NEW_THREADS)
    assert fb.booting() is False


def test_a_boot_that_the_environment_skips_starts_nothing(wired, monkeypatch):
    monkeypatch.setenv("CLOUDE_SAVE_PIPELINE", "0")
    assert wiring.install() is False
    assert not (_names() & NEW_THREADS) and runtime.current() is None


def _stats_rows(state: Path) -> int:
    db = state / "pipeline-plugins" / "stats.db"
    if not db.exists():
        return 0
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as conn:
        return conn.execute("SELECT COUNT(*) FROM dim_source").fetchone()[0]


@pytest.mark.skipif(not KQUEUE_AVAILABLE, reason="the file trigger is kqueue; without it the watcher uses its tick")
def test_a_line_appended_through_the_real_file_trigger_becomes_a_stats_row_in_under_5_seconds_with_no_scan(wired, tmp_path):
    folder = (tmp_path / "projects" / K.CLAUDE_FOLDER).resolve()
    sub = folder / K.MAIN / "subagents"
    sub.mkdir(parents=True)
    main = folder / f"{K.MAIN}.jsonl"
    main.write_bytes(K.claude_main(2))
    engine = Engine(wired.state, db_path=wired.db, plugins=registry.plugins(), scan_interval=3600.0)
    feed = LiveFeed(paths_for=lambda: (lambda sid: (str(main), str(sub))), engine=lambda: engine)

    async def scenario() -> float:
        engine.start()
        while engine.scan_ticks < 1:
            await asyncio.sleep(0.02)
        assert _stats_rows(wired.state) == 0
        fired = []
        trigger = FsTrigger(lambda ids: [fired.append(i) or feed.on_observation(
            i, SimpleNamespace(transcript_appended=True), "idle") for i in ids], quiet_seconds=0.05, max_wait_seconds=0.2)
        assert trigger.start()
        trigger.rearm({str(main): ["ses_1"]})
        started = time.monotonic()
        with open(main, "ab") as handle:
            handle.write(K.jl(K.assistant(9, K.MAIN, 5, 33)))
        while _stats_rows(wired.state) == 0 and time.monotonic() - started < 5:
            await asyncio.sleep(0.05)
        trigger.close()
        assert fired == ["ses_1"]
        return time.monotonic() - started

    try:
        elapsed = asyncio.run(scenario())
    finally:
        engine.stop()
    assert _stats_rows(wired.state) == 1 and elapsed < 5
    assert engine.scan_ticks == 1


def test_a_working_session_is_looked_at_for_new_sub_agent_files_and_an_idle_one_costs_nothing(wired, tmp_path):
    folder = (tmp_path / "p" / K.CLAUDE_FOLDER).resolve()
    sub = folder / K.MAIN / "subagents"
    sub.mkdir(parents=True)
    main = folder / f"{K.MAIN}.jsonl"
    main.write_bytes(K.claude_main(1))
    agent = sub / "agent-1.jsonl"
    agent.write_bytes(K.claude_subagent())
    engine = Engine(wired.state, db_path=wired.db, plugins=registry.plugins(), scan_interval=3600.0)
    now = [100.0]
    feed = LiveFeed(paths_for=lambda: (lambda sid: (str(main), str(sub))), engine=lambda: engine,
                    clock=lambda: now[0])

    async def scenario() -> None:
        feed.on_observation("ses_1", SimpleNamespace(transcript_appended=False), "idle")
        await asyncio.sleep(0.1)
        assert feed.counters["looks"] == 0 and engine.dirty.size() == 0
        feed.on_observation("ses_1", SimpleNamespace(transcript_appended=False), "working")
        await asyncio.sleep(0.3)
        assert feed.counters["looks"] == 1 and engine.dirty.size() == 2
        feed.on_observation("ses_1", SimpleNamespace(transcript_appended=False), "working")
        await asyncio.sleep(0.1)
        assert feed.counters["looks"] == 1
        now[0] += 3
        feed.on_observation("ses_1", SimpleNamespace(transcript_appended=False), "idle")
        await asyncio.sleep(0.3)
        assert feed.counters["looks"] == 2

    asyncio.run(scenario())


def test_a_trigger_is_one_idempotent_milestone_and_a_refusal_is_a_refused_result(wired):
    row = {"session_uuid": "s-1", "claude_session_uuid": "conv-9", "host_key": "local"}
    done = triggers.enqueue("kill", lambda conn: row)
    assert done.result(timeout=10).state == "done"
    refused = triggers.enqueue("kill", lambda conn: None)
    assert refused.result(timeout=10).state == triggers.STATE_REFUSED
    remote = triggers.enqueue("sleep", lambda conn: dict(row, host_key="mac2"))
    assert remote.result(timeout=10).state == triggers.STATE_REFUSED
    no_lineage = triggers.enqueue("kill", lambda conn: None, record_lineage=False)
    assert no_lineage.result(timeout=10).state == "done"
    with closing(sqlite3.connect(wired.db)) as conn:
        rows = conn.execute("SELECT conversation_id, kind FROM conversation_milestones").fetchall()
    assert rows == [("conv-9", "kill")]
    assert not (_names() & NEW_THREADS)


def _wait_until(done, timeout: float = 10.0) -> None:
    end = time.monotonic() + timeout
    while not done() and time.monotonic() < end:
        time.sleep(0.01)


def test_a_lifecycle_event_reaches_the_save_seam_exactly_once_and_only_after_the_milestone_is_written(wired):
    from src.cplugs.sdk import save_triggers

    seen = []

    def listener(save):
        with closing(sqlite3.connect(wired.db)) as conn:
            seen.append((save, conn.execute("SELECT conversation_id, kind FROM conversation_milestones").fetchall()))

    stop = save_triggers.subscribe(listener)
    try:
        row = {"session_uuid": "s-1", "claude_session_uuid": "conv-9", "host_key": "local", "agent_family": "claude",
               "working_dir": "/p", "agent_type": "claude", "title": "t"}
        assert triggers.enqueue("kill", lambda conn: row).result(timeout=10).state == "done"
        _wait_until(lambda: seen)
    finally:
        stop()
    assert len(seen) == 1
    save, rows_at_announce = seen[0]
    assert rows_at_announce == [("conv-9", "kill")]
    assert (save.event, save.conversation_id, save.session_uuid, save.family) == ("kill", "conv-9", "s-1", "claude")
    assert save.facts == {"working_dir": "/p", "wrapper": "claude", "title": "t"}


def test_a_failing_listener_never_fails_or_repeats_the_milestone(wired):
    from src.cplugs.sdk import save_triggers

    calls = []
    stop = save_triggers.subscribe(lambda save: calls.append(1) or (_ for _ in ()).throw(RuntimeError("boom")))
    try:
        row = {"session_uuid": "s-2", "claude_session_uuid": "conv-8", "host_key": "local"}
        assert triggers.enqueue("sleep", lambda conn: row).result(timeout=10).state == "done"
        _wait_until(lambda: calls)
    finally:
        stop()
    assert calls == [1]
    with closing(sqlite3.connect(wired.db)) as conn:
        assert conn.execute("SELECT conversation_id, kind FROM conversation_milestones").fetchall() == [("conv-8", "sleep")]


def test_status_and_rebuild_go_to_the_running_engine(wired):
    assert runtime.status() == {"state": "off"}
    runtime.start(wired.state, wired.db)
    body = runtime.status()
    assert body["state"] in ("caught_up", "behind") and "stats" in body["plugins"] and "engine" not in body
    out = runtime.rebuild_plugin("stats")
    assert out["plugin"] == "stats" and out["dropped_bytes"] >= 0
    runtime.stop()
    assert runtime.status() == {"state": "off"}


def test_a_file_bigger_than_one_runs_byte_budget_is_requeued_and_finishes_with_no_scan(tmp_path, monkeypatch):
    from tests.pipeline.test_engine import drain, make, transcript
    from src.core.pipeline import deliver

    monkeypatch.setattr(deliver.Budget.__init__, "__defaults__", (3000,))
    fake, plugin, engine = make(tmp_path)
    target = transcript(tmp_path / "c", "big.jsonl", 120)
    size = Path(target.path).stat().st_size
    assert size > 3 * 3000
    engine.mark_dirty(target)
    steps = 0
    while engine.dirty.size() and steps < 200:
        engine.step()
        steps += 1
    assert plugin.counts(engine.state_dir) == {target.path: 120}
    assert steps > 3 and plugin.cursor_offsets(engine.state_dir) == {target.path: size}
    assert engine.dirty.size() == 0 and drain(engine) is None
