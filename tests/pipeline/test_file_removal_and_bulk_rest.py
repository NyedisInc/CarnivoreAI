
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import List

from src.core.pipeline import contract as C
from src.core.pipeline import engine as engine_mod
from src.core.pipeline import observe, scan
from src.core.pipeline.deliver import FileTarget
from src.core.pipeline.engine import Engine
from src.core.transcript_manifest import constants as TM
from tests.pipeline.test_engine import Counting, Fake, drain, make, transcript


class Removing(Counting):

    def __init__(self, pid: str, per_file: bool) -> None:
        super().__init__(pid)
        self.told: List[tuple] = []
        self.plugin = replace(self.plugin, on_events=self.on_events, per_file_removal=per_file)

    def on_events(self, conn, events):
        for ev in events:
            if isinstance(ev, C.FileRemoved):
                self.told.append(("file", ev.path))
                conn.execute("DELETE FROM lines WHERE path = ?", (ev.path,))
            elif isinstance(ev, C.ConversationRemoved):
                self.told.append(("conversation", ev.conversation_id))
                conn.execute("DELETE FROM lines")
        super().on_events(conn, tuple(e for e in events if isinstance(e, (C.Appended, C.FileReset))))


def test_a_gone_file_is_told_to_a_per_file_plugin_only_and_only_for_that_path(tmp_path):
    fake = Fake()
    per_file, per_conversation = Removing("perfile", True), Removing("perconv", False)
    engine = Engine(tmp_path / "state", plugins=[per_file.plugin, per_conversation.plugin], clock=fake.mono, wall=fake.wall)
    first = transcript(tmp_path / "copy-a", "c1.jsonl", 3)
    second = transcript(tmp_path / "copy-b", "c1.jsonl", 4)
    for target in (first, second):
        engine.mark_dirty(target)
    drain(engine)
    Path(first.path).unlink()
    engine.mark_file_removed(first)
    engine.mark_removed(first.conversation_id, "claude")
    fake.advance(10.0)
    drain(engine)
    assert per_file.told == [("file", first.path)]
    assert per_conversation.told == [("conversation", "c1")]
    assert per_file.counts(engine.state_dir) == {second.path: 4}
    assert first.path not in {r[0] for r in _cursors(engine, per_file)}


def test_a_file_back_on_disk_is_not_removed(tmp_path):
    fake = Fake()
    plugin = Removing("perfile", True)
    engine = Engine(tmp_path / "state", plugins=[plugin.plugin], clock=fake.mono, wall=fake.wall)
    target = transcript(tmp_path / "copy-a", "c2.jsonl", 2)
    engine.mark_dirty(target)
    drain(engine)
    engine.mark_file_removed(target)
    fake.advance(10.0)
    drain(engine)
    assert plugin.told == [] and plugin.counts(engine.state_dir) == {target.path: 2}


def test_the_scan_names_a_gone_file_only_when_a_cursor_holds_it():
    def row(path: str, gone: bool) -> scan.ManifestFile:
        return scan.ManifestFile(path, "c", C.FAMILY_CLAUDE, TM.KIND_CONVERSATION, False, gone, 10)

    rows = [row("/a/c.jsonl", True), row("/b/c.jsonl", False), row("/c/never-read.jsonl", True)]
    cursors = {"/a/c.jsonl": (10, "c"), "/b/c.jsonl": (10, "c")}
    assert [r.path for r in scan.removed_files(rows, cursors)] == ["/a/c.jsonl"]
    assert scan.removed_conversations(rows, cursors) == {}


def test_a_bulk_backfill_rests_between_batches_and_a_live_key_still_goes_first(tmp_path, monkeypatch):
    fake, plugin, engine = make(tmp_path)
    monkeypatch.setattr(engine_mod, "BATCH_KEYS", 1)
    real = engine._deliver_batch

    def slow(entries):
        real(entries)
        fake.advance(4.0)

    monkeypatch.setattr(engine, "_deliver_batch", slow)
    backlog = [transcript(tmp_path / "c", f"b{i}.jsonl", 2) for i in range(3)]
    live = transcript(tmp_path / "c", "live.jsonl", 2)
    for target in backlog:
        engine.mark_dirty(target, observe.TRIGGER_SCAN)
    engine.step()
    assert len(plugin.counts(engine.state_dir)) == 1
    delay = engine.step()
    assert len(plugin.counts(engine.state_dir)) == 1 and 0 < delay <= C.BULK_REST_MAX_SECONDS
    engine.mark_dirty(live)
    engine.step()
    assert plugin.counts(engine.state_dir).get(live.path) == 2 and len(plugin.counts(engine.state_dir)) == 2
    fake.advance(10.0)
    engine.step()
    assert len(plugin.counts(engine.state_dir)) == 3


def test_a_bulk_only_batch_gives_way_the_moment_a_live_key_is_due(tmp_path):
    fake, plugin, engine = make(tmp_path)
    backlog = [transcript(tmp_path / "c", f"b{i}.jsonl", 2) for i in range(4)]
    live = transcript(tmp_path / "c", "live.jsonl", 2)
    for target in backlog:
        engine.mark_dirty(target, observe.TRIGGER_SCAN)
    real = engine._deliver_entry
    delivered: List[str] = []

    def deliver_then_a_live_key_arrives(delivery, entry):
        real(delivery, entry)
        delivered.append(entry.key[1])
        if len(delivered) == 1:
            engine.mark_dirty(live)

    engine._deliver_entry = deliver_then_a_live_key_arrives
    engine.step()
    assert delivered == [backlog[0].path]
    assert engine.dirty.size() == 4
    engine.step()
    assert delivered[1] == live.path


def test_rapid_settings_saves_start_one_rescan_thread_and_one_more_pass(tmp_path, monkeypatch):
    import threading

    fake, plugin, engine = make(tmp_path)
    started, release, passes = threading.Event(), threading.Event(), []

    def slow_pass():
        passes.append(1)
        started.set()
        release.wait(10)
        return {}

    monkeypatch.setattr(engine.scanner, "mark_pass", slow_pass)
    engine.rescan()
    assert started.wait(10)
    for _ in range(5):
        engine.rescan()
    assert len([t for t in threading.enumerate() if t.name == "pipeline-rescan"]) == 1
    release.set()
    for thread in [t for t in threading.enumerate() if t.name == "pipeline-rescan"]:
        thread.join(10)
    assert len(passes) == 2
    engine.rescan()
    for thread in [t for t in threading.enumerate() if t.name == "pipeline-rescan"]:
        thread.join(10)
    assert len(passes) == 3


def _cursors(engine: Engine, plugin: Removing) -> list:
    import sqlite3
    from contextlib import closing

    from src.core.pipeline import plugin_db

    with closing(sqlite3.connect(plugin_db.db_path(engine.state_dir, plugin.plugin))) as conn:
        return conn.execute(f"SELECT path, conversation_id FROM {C.CURSORS_TABLE}").fetchall()
