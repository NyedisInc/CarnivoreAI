
from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.attention.display import to_display
from src.core.attention.fs_trigger import KQUEUE_AVAILABLE, FsTrigger
from src.core.pipeline import registry, scan
from src.core.pipeline.engine import Engine
from src.core.pipeline.feed import LiveFeed
from tests import test_codex_listing_integration as L
from tests.pipeline import corpus as K
from tests.s7_helpers import migrated_connection


@pytest.fixture()
def codex_world(tmp_path, monkeypatch):
    from src.core.db import db_path_for
    state = tmp_path / "pstate"
    state.mkdir()
    migrated_connection(state).close()
    monkeypatch.setattr(scan.Scanner, "_walk", lambda self: SimpleNamespace(changed=()))
    home = L._make_home(tmp_path, turns=[("completed", None)], lock=True)
    rollout = home / "sessions" / "2026" / "09" / "12" / f"rollout-2026-09-12T10-48-49-{L.THREAD}.jsonl"
    rollout.write_bytes(K.codex_rollout())
    watcher, clock, _row = L._pipeline(tmp_path, monkeypatch, home)
    reader = watcher._read_evidence
    yield SimpleNamespace(state=state, db=db_path_for(state), watcher=watcher, clock=clock, reader=reader,
                          rollout=rollout, real=os.path.realpath(rollout))


def _cursor_offset(state: Path, real: str):
    db = state / "pipeline-plugins" / "stats.db"
    if not db.exists():
        return None
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as conn:
        row = conn.execute("SELECT offset FROM plugin_cursors WHERE path = ?", (real,)).fetchone()
    return row[0] if row else None


def test_the_reader_maps_a_codex_session_to_its_rollout_and_watches_it_only_for_the_new_engine(codex_world):
    w = codex_world
    asyncio.run(w.watcher.tick_once())
    assert w.reader.rollout_for(L.SESSION_ID) == str(w.rollout)
    assert w.reader.paths_for(L.SESSION_ID) is None
    assert str(w.rollout) not in w.reader.watch_paths({L.SESSION_ID}).get(L.SESSION_ID, ())
    w.reader._watch_codex_rollouts = lambda: True
    assert str(w.rollout) in w.reader.watch_paths({L.SESSION_ID})[L.SESSION_ID]
    assert w.reader.watch_paths(set()) == {} and w.reader.rollout_for(L.SESSION_ID) is None


@pytest.mark.skipif(not KQUEUE_AVAILABLE, reason="the file trigger is kqueue; without it the watcher uses its tick")
def test_an_append_to_a_live_codex_rollout_is_delivered_in_under_5_seconds_with_no_scan(codex_world):
    w = codex_world
    w.reader._watch_codex_rollouts = lambda: True
    engine = Engine(w.state, db_path=w.db, plugins=registry.plugins(), scan_interval=3600.0)
    feed = LiveFeed(paths_for=lambda: w.reader.paths_for, rollout_for=lambda: w.reader.rollout_for,
                    engine=lambda: engine)
    inner = w.watcher._on_observation

    def on_observation(target, observation):
        inner(target, observation)
        feed.on_observation(target.session_id, observation, to_display(observation.verdict, unread=False,
                                                                       tmux_status="running"))
    w.watcher._on_observation = on_observation

    async def wait_for(check, seconds: float = 5.0) -> float:
        started = time.monotonic()
        while not check():
            assert time.monotonic() - started < seconds, "not delivered in time"
            await asyncio.sleep(0.05)
        return time.monotonic() - started

    async def scenario() -> float:
        engine.start()
        while engine.scan_ticks < 1:
            await asyncio.sleep(0.02)
        w.clock[0] = L.NOW + timedelta(seconds=1)
        await w.watcher.tick_once()
        await wait_for(lambda: _cursor_offset(w.state, w.real) == w.rollout.stat().st_size)
        assert _cursor_offset(w.state, w.real) > 0
        trigger = FsTrigger(lambda ids: asyncio.get_running_loop().create_task(w.watcher.tick_once()),
                            quiet_seconds=0.05, max_wait_seconds=0.2)
        assert trigger.start()
        trigger.rearm({p: [sid] for sid, paths in w.reader.watch_paths({L.SESSION_ID}).items() for p in paths})
        assert str(w.rollout) in trigger.watched_paths()
        before = w.rollout.stat().st_size
        w.clock[0] = L.NOW + timedelta(seconds=3)
        started = time.monotonic()
        with open(w.rollout, "ab") as handle:
            handle.write(K.jl({"type": "event_msg", "timestamp": L.NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), "payload": {
                "type": "token_count", "info": {"total_token_usage": {
                    "input_tokens": 4000, "cached_input_tokens": 900, "output_tokens": 200,
                    "reasoning_output_tokens": 0}}}}))
        grown = w.rollout.stat().st_size
        assert grown > before
        await wait_for(lambda: _cursor_offset(w.state, w.real) == grown)
        trigger.close()
        return time.monotonic() - started

    try:
        elapsed = asyncio.run(scenario())
    finally:
        engine.stop()
    assert elapsed < 5
    assert engine.scan_ticks == 1
