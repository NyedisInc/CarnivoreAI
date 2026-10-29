
import importlib
import json
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional, Set

import pytest

from src.core.pipeline import contract as C
from src.core.pipeline import deliver, observe, plugin_db, reader, registry, status
from src.core.pipeline.engine import THREAD_SCAN, THREAD_WORKER, Engine
from src.core.pipeline.lifecycle import Lifecycle, iso
from src.core.pipeline.observe import classify
from src.core.pipeline.rebuild import UnknownPlugin
from tests.pipeline import corpus as K
from tests.s7_helpers import migrated_connection


class Fake:

    def __init__(self) -> None:
        self.t = 0.0

    def mono(self) -> float:
        return self.t

    def wall(self) -> float:
        return 1_700_000_000.0 + self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class Counting:

    def __init__(self, pid: str = "count") -> None:
        self.fail: Set[str] = set()
        self.attempts: Dict[str, int] = {}
        self.hooks: List[tuple] = []
        self.plugin = C.Plugin(pid, f"{pid}.db", 1, self.migrate, self.on_events, self.carry_over,
                               on_lifecycle=self.on_lifecycle)

    def migrate(self, conn, from_version):
        conn.execute("CREATE TABLE lines (path TEXT NOT NULL, off INTEGER NOT NULL)")
        conn.execute("CREATE TABLE settings (k TEXT PRIMARY KEY, v TEXT)")

    def on_events(self, conn, events):
        for ev in events:
            if isinstance(ev, C.Appended):
                self.attempts[ev.path] = self.attempts.get(ev.path, 0) + 1
                if ev.path in self.fail:
                    raise RuntimeError("poison file")
                conn.executemany("INSERT INTO lines VALUES (?, ?)", [(ev.path, line.offset) for line in ev.lines])
            elif isinstance(ev, C.FileReset):
                conn.execute("DELETE FROM lines WHERE path = ?", (ev.path,))
            else:
                conn.executemany("DELETE FROM lines WHERE path = ?", [(p,) for p in ev.paths])

    def carry_over(self, old, new):
        new.executemany("INSERT INTO settings VALUES (?, ?)", old.execute("SELECT k, v FROM settings").fetchall())

    def on_lifecycle(self, conn, kind, conversation_id, at_ts, payload):
        self.hooks.append((kind, conversation_id, at_ts))

    def counts(self, state_dir: Path) -> Dict[str, int]:
        with closing(sqlite3.connect(plugin_db.db_path(state_dir, self.plugin))) as conn:
            return dict(conn.execute("SELECT path, COUNT(*) FROM lines GROUP BY path"))

    def cursor_offsets(self, state_dir: Path) -> Dict[str, int]:
        with closing(sqlite3.connect(plugin_db.db_path(state_dir, self.plugin))) as conn:
            return dict(conn.execute(f"SELECT path, offset FROM {C.CURSORS_TABLE}"))


def transcript(folder: Path, name: str, lines: int, session: str = K.MAIN) -> C.Appended:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(K.jl(*[K.user(i, session, 1) for i in range(lines)]))
    return deliver.FileTarget(str(path), name.split("/")[-1][:-6], C.FAMILY_CLAUDE, C.FILE_CONVERSATION)


def drain(engine: Engine) -> Optional[float]:
    for _ in range(400):
        delay = engine.step()
        if delay is None or delay > 0:
            return delay
    raise AssertionError("the worker never ran out of due work")


def make(tmp_path, plugin=None, **kw):
    fake, plugin = Fake(), plugin or Counting()
    engine = Engine(tmp_path / "state", plugins=[plugin.plugin], clock=fake.mono, wall=fake.wall, **kw)
    return fake, plugin, engine


def test_a_poison_file_backs_off_and_is_retried_while_the_rest_finish_and_nothing_is_skipped(tmp_path):
    fake, plugin, engine = make(tmp_path)
    files = [transcript(tmp_path / "c", f"good{i}.jsonl", 30 + i) for i in range(3)]
    poison = transcript(tmp_path / "c", "poison.jsonl", 5)
    plugin.fail.add(poison.path)
    created = [engine.mark_dirty(files[i % 3]) for i in range(1000)] + [engine.mark_dirty(poison)]
    assert sum(created) == 4 and engine.dirty.size() == 4
    delay = drain(engine)
    counts = plugin.counts(engine.state_dir)
    assert [counts[f.path] for f in files] == [30, 31, 32] and poison.path not in counts
    assert plugin.attempts[poison.path] == 1 and delay == pytest.approx(5.0)
    state = engine.status()
    assert state["state"] == "behind" and state["parked_files"] == 1
    assert state["plugins"]["count"]["failures"] == 1 and "poison file" in state["plugins"]["count"]["last_error"]
    for _ in range(100):
        engine.mark_dirty(poison)
    assert drain(engine) == pytest.approx(2.0) and plugin.attempts[poison.path] == 1
    fake.advance(2.0)
    assert drain(engine) == pytest.approx(3.0) and plugin.attempts[poison.path] == 1
    waits = []
    for _ in range(8):
        fake.advance(waits[-1] if waits else 3.0)
        waits.append(drain(engine))
    assert waits == pytest.approx([10, 20, 40, 80, 160, 300, 300, 300]) and plugin.attempts[poison.path] == 9
    plugin.fail.clear()
    fake.advance(300.0)
    assert drain(engine) is None
    assert plugin.counts(engine.state_dir)[poison.path] == 5
    assert plugin.cursor_offsets(engine.state_dir)[poison.path] == Path(poison.path).stat().st_size
    assert engine.status()["state"] == "caught_up" and engine.status()["plugins"]["count"]["failures"] == 0


def test_a_thousand_files_are_delivered_in_batches_with_one_poison_file_parked(tmp_path):
    fake, plugin, engine = make(tmp_path)
    targets = [transcript(tmp_path / "c", f"f{i:04d}.jsonl", 2) for i in range(1000)]
    plugin.fail.add(targets[500].path)
    for target in targets:
        engine.mark_dirty(target)
    steps = 0
    while engine.dirty.next_delay() == 0.0:
        engine.step()
        steps += 1
    assert steps >= 1000 // 64
    counts = plugin.counts(engine.state_dir)
    assert len(counts) == 999 and all(n == 2 for n in counts.values()) and targets[500].path not in counts
    assert engine.dirty.size() == 1 and engine.status()["parked_files"] == 1


def test_a_hung_read_parks_the_key_and_it_is_retried_from_the_cursor(tmp_path, monkeypatch):
    fake, plugin, engine = make(tmp_path)
    hung, fine = transcript(tmp_path / "c", "hung.jsonl", 4), transcript(tmp_path / "c", "fine.jsonl", 4)
    release, real = threading.Event(), reader.read_slice
    monkeypatch.setattr(C, "READ_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(reader, "read_slice", lambda p, *a: (release.wait(5) and b"") if p == hung.path else real(p, *a))
    engine.mark_dirty(hung)
    engine.mark_dirty(fine)
    assert drain(engine) == pytest.approx(5.0)
    assert plugin.counts(engine.state_dir) == {fine.path: 4}
    state = engine.status()
    assert state["parked_files"] == 1 and state["plugins"]["count"]["failures"] == 0
    release.set()
    monkeypatch.setattr(reader, "read_slice", real)
    for _ in range(200):
        if reader.hung_helpers() == 0:
            break
        time.sleep(0.01)
    fake.advance(5.0)
    assert drain(engine) is None and plugin.counts(engine.state_dir)[hung.path] == 4


def test_exactly_one_delivery_worker_thread_and_one_scan_thread(tmp_path):
    def named(name):
        return [t for t in threading.enumerate() if t.name == name]

    def delivered(target):
        try:
            return plugin.counts(engine.state_dir).get(target.path)
        except sqlite3.OperationalError:
            return None

    plugin = Counting()
    engine = Engine(tmp_path / "state", plugins=[plugin.plugin])
    assert not named(THREAD_WORKER)
    engine.start()
    engine.start()
    try:
        assert len(named(THREAD_WORKER)) == 1 and len(named(THREAD_SCAN)) == 1
        assert not named("pipeline-lifecycle")
        target = transcript(tmp_path / "c", "live.jsonl", 6)
        engine.mark_dirty(target)
        deadline = time.time() + 10
        while time.time() < deadline and delivered(target) != 6:
            time.sleep(0.05)
        assert delivered(target) == 6
        assert engine.status()["threads"] == {"worker": True, "scan": True, "lifecycle": False}
    finally:
        engine.stop()
    assert not named(THREAD_WORKER) and not named(THREAD_SCAN)


def test_an_idle_engine_never_wakes_without_an_edge_except_the_scan_tick(tmp_path):
    fake, plugin = Fake(), Counting()
    state = tmp_path / "state"
    state.mkdir()
    migrated_connection(state).close()
    waits = {"worker": [], "scan": []}
    END = 600.0

    def wait(event, timeout):
        who = "worker" if event is engine._wake else "scan"
        waits[who].append(timeout)
        if timeout is None or fake.t >= END:
            return event.wait()
        fake.advance(timeout)
        return False

    from src.core.db import db_path_for
    engine = Engine(state, db_path=db_path_for(state), plugins=[plugin.plugin], clock=fake.mono, wall=fake.wall,
                    wait=wait, refresh_fn=lambda: SimpleNamespace(changed=[]))
    engine.start()
    try:
        deadline = time.time() + 10
        while engine.scan_ticks < 3 and time.time() < deadline:
            time.sleep(0.02)
        assert engine.scan_ticks == 3 and fake.t == END
        assert engine.scanner.last["status"] == "ok" and waits["scan"][:3] == [300.0] * 3
        assert waits["worker"] == [None] and engine.wakes == 0
        target = transcript(tmp_path / "c", "edge.jsonl", 3)
        engine.mark_dirty(target)
        deadline = time.time() + 10
        while engine.wakes < 1 and time.time() < deadline:
            time.sleep(0.02)
        time.sleep(0.3)
        assert engine.wakes == 1 and waits["worker"] == [None, None]
        assert plugin.counts(state)[target.path] == 3
        plugin.fail.add(target.path)
        target2 = transcript(tmp_path / "c", "later.jsonl", 3)
        plugin.fail.add(target2.path)
        engine.mark_dirty(target2)
        deadline = time.time() + 10
        while len([w for w in waits["worker"] if w is not None]) < 1 and time.time() < deadline:
            time.sleep(0.02)
        assert any(w is not None and w > 0 for w in waits["worker"])
    finally:
        engine.stop()


def _milestone_rows(db: Path) -> List[tuple]:
    with closing(sqlite3.connect(db)) as conn:
        return conn.execute("SELECT conversation_id, kind, at_ts FROM conversation_milestones "
                            "ORDER BY kind, at_ts").fetchall()


def test_two_lifecycle_events_for_one_conversation_in_one_tick_write_two_rows(tmp_path):
    from src.core.db import db_path_for
    state = tmp_path / "state"
    state.mkdir()
    migrated_connection(state).close()
    engine = Engine(state, db_path=db_path_for(state), plugins=[])
    tick = 1_790_000_000.0
    futures = [engine.write_milestone("sleep", "conv-1", tick, {"session_uuid": "s1"}),
               engine.write_milestone("kill", "conv-1", tick, {"session_uuid": "s1"}),
               engine.write_milestone("kill", "conv-1", tick, {"session_uuid": "s1"}),
               engine.write_milestone("restart", "conv-2", tick + 1, {"session_uuid": "s2"})]
    assert [f.result(timeout=10) for f in futures] == ["written", "written", "present", "written"]
    rows = _milestone_rows(db_path_for(state))
    assert rows == [("conv-1", "kill", iso(tick)), ("conv-2", "restart", iso(tick + 1)), ("conv-1", "sleep", iso(tick))]
    deadline = time.time() + 5
    while engine.lifecycle.alive() and time.time() < deadline:
        time.sleep(0.02)
    assert not engine.lifecycle.alive()


def test_a_failed_milestone_write_is_retried_with_the_same_time_and_the_plugin_hook_runs_once(tmp_path):
    plugin, calls = Counting(), []

    def writer(db, kind, conv, session, **kw):
        calls.append((kind, conv, session, kw["at_ts"]))
        if len(calls) < 3:
            raise sqlite3.OperationalError("database is locked")
        return "written"

    life = Lifecycle(tmp_path / "x.db", state_dir=tmp_path / "state", plugins=[plugin.plugin], writer=writer,
                     retry_delays=(0.01,))
    assert life.write_milestone("kill", "c9", 1_790_000_000.5, {"session_uuid": "s9"}).result(timeout=10) == "written"
    assert len(calls) == 3 and len({c[3] for c in calls}) == 1 and calls[0][3] == iso(1_790_000_000.5)
    assert plugin.hooks == [("kill", "c9", 1_790_000_000.5)]


def test_the_scan_marks_what_is_behind_and_delivers_nothing(tmp_path):
    from src.core.db import db_path_for
    fake, plugin, engine0 = make(tmp_path)
    state = engine0.state_dir
    state.mkdir(exist_ok=True)
    caught, behind_t = transcript(tmp_path / "c", "caught.jsonl", 3), transcript(tmp_path / "c", "behind.jsonl", 3)
    gone_main = transcript(tmp_path / "c", "gone.jsonl", 2)
    for t in (caught, gone_main):
        engine0.mark_dirty(t)
    assert drain(engine0) is None
    migrated_connection(state).close()
    db = db_path_for(state)
    size = lambda t: Path(t.path).stat().st_size  # noqa: E731
    with closing(sqlite3.connect(db)) as conn:
        for t, nbytes, gone_at in ((caught, size(caught), None), (behind_t, size(behind_t), None),
                                   (gone_main, size(gone_main), "2026-10-12T00:00:00+00:00")):
            conn.execute("INSERT INTO transcript_files (path, family, root, source_path, conversation_id, kind, size, "
                         "mtime_ns, complete_bytes, status, first_seen, last_seen, changed_at, gone_at) "
                         "VALUES (?, 'claude', '/r', ?, ?, 'conversation', ?, 1, ?, 'present', 't', 't', 't', ?)",
                         (t.path, t.path, t.conversation_id, nbytes, nbytes, gone_at))
        conn.commit()
    fake2 = Fake()
    engine = Engine(state, db_path=db, plugins=[plugin.plugin], clock=fake2.mono, wall=fake2.wall,
                    refresh_fn=lambda: SimpleNamespace(changed=[]))
    before = plugin.counts(state)
    record = engine.scanner.run_once()
    assert record["status"] == "ok" and record["files"] == 3
    assert record["marked"] == 1 and record["removed"] == 1
    pending = {e.key for e in engine.dirty.take(10)}
    assert pending == {(observe.KIND_FILE, behind_t.path), (observe.KIND_REMOVED, gone_main.conversation_id)}
    assert plugin.counts(state) == before
    failing = Engine(state, db_path=db, plugins=[plugin.plugin],
                     refresh_fn=lambda: (_ for _ in ()).throw(OSError("walk failed")))
    assert failing.scanner.run_once()["status"] == "failed"


def test_a_rebuild_swaps_the_plugin_database_carries_its_settings_and_replays_the_files(tmp_path):
    from src.core.db import db_path_for
    fake = Fake()
    state = tmp_path / "state"
    state.mkdir()
    migrated_connection(state).close()
    db = db_path_for(state)
    plugin = Counting()
    files = [transcript(tmp_path / "c", f"r{i}.jsonl", 4 + i) for i in range(3)]
    with closing(sqlite3.connect(db)) as conn:
        for t in files:
            n = Path(t.path).stat().st_size
            conn.execute("INSERT INTO transcript_files (path, family, root, source_path, conversation_id, kind, size, "
                         "mtime_ns, complete_bytes, status, first_seen, last_seen, changed_at) "
                         "VALUES (?, 'claude', '/r', ?, ?, 'conversation', ?, 1, ?, 'present', 't', 't', 't')",
                         (t.path, t.path, t.conversation_id, n, n))
        conn.commit()
    engine = Engine(state, db_path=db, plugins=[plugin.plugin], clock=fake.mono, wall=fake.wall)
    for t in files:
        engine.mark_dirty(t)
    assert drain(engine) is None and sum(plugin.counts(state).values()) == 4 + 5 + 6
    with closing(sqlite3.connect(plugin_db.db_path(state, plugin.plugin))) as conn:
        conn.execute("INSERT INTO settings VALUES ('price', 'v7')")
        conn.commit()
    seen = {}
    original = plugin.carry_over

    def carry(old, new):
        seen["state"] = engine2.status()["state"]
        seen["paused"] = "count" in engine2._paused
        original(old, new)

    plugin.plugin = C.Plugin("count", "count.db", 1, plugin.migrate, plugin.on_events, carry)
    engine2 = Engine(state, db_path=db, plugins=[plugin.plugin], clock=fake.mono, wall=fake.wall)
    with pytest.raises(UnknownPlugin):
        engine2.rebuild_plugin("nope")
    result = engine2.rebuild_plugin("count")
    assert result["files_marked"] == 3 and seen == {"state": "rebuilding", "paused": True}
    assert plugin.counts(state) == {}
    with closing(sqlite3.connect(plugin_db.db_path(state, plugin.plugin))) as conn:
        assert conn.execute("SELECT v FROM settings WHERE k = 'price'").fetchone() == ("v7",)
    assert engine2.status()["state"] == "rebuilding" and engine2.dirty.size() == 3
    assert drain(engine2) is None
    assert sorted(plugin.counts(state).values()) == [4, 5, 6]
    assert engine2.status()["state"] == "caught_up" and not engine2.status()["rebuilding"]


def test_status_names_caught_up_behind_stalled_and_rebuilding(tmp_path):
    fake, plugin, engine = make(tmp_path)
    assert engine.status()["state"] == "caught_up" and engine.status()["lag"] == {"files": 0, "seconds": 0.0}
    target = transcript(tmp_path / "c", "s.jsonl", 3)
    plugin.fail.add(target.path)
    engine.mark_dirty(target)
    fake.advance(30.0)
    assert engine.status()["state"] == "behind" and engine.status()["lag"] == {"files": 1, "seconds": 30.0}
    drain(engine)
    fake.advance(status.STALL_AFTER_SECONDS + 1)
    stalled = engine.status()
    assert stalled["state"] == "stalled" and stalled["stalled_since"] == pytest.approx(fake.wall() - 301.0 - 0.0)
    assert stalled["last_delivery_at"] is None
    plugin.fail.clear()
    fake.advance(300.0)
    assert drain(engine) is None
    done = engine.status()
    assert done["state"] == "caught_up" and done["stalled_since"] is None and done["last_delivery_age"] == 0.0
    engine.begin_rebuild("count")
    assert engine.status()["state"] == "rebuilding" and engine.status()["plugins"]["count"]["rebuilding"]


def test_the_registry_is_a_static_tuple_that_starts_nothing_and_refuses_a_duplicate():
    before = threading.active_count()
    importlib.reload(registry)
    assert threading.active_count() == before and isinstance(registry.PLUGINS, tuple)
    one = Counting().plugin
    assert registry.plugins([one]) == (one,) and registry.find("count", [one]) is one and registry.find("x", [one]) is None
    with pytest.raises(C.PluginContractError):
        registry.plugins([one, one])


def test_the_observer_classifies_a_path_and_marks_only_files_that_changed(tmp_path):
    root = tmp_path / ".claude" / "projects" / "-slug"
    sub = root / "conv-9" / "subagents"
    main = root / "conv-9.jsonl"
    sub.mkdir(parents=True)
    main.write_bytes(b'{"a": 1}\n')
    (sub / "agent-1.jsonl").write_bytes(b'{"a": 1}\n')
    assert classify(str(main)).conversation_id == "conv-9" and classify(str(main)).file_kind == C.FILE_CONVERSATION
    agent = classify(str(sub / "agent-1.jsonl"))
    assert (agent.conversation_id, agent.file_kind, agent.family) == ("conv-9", C.FILE_SUBAGENT, C.FAMILY_CLAUDE)
    rollout = classify("/h/.codex/sessions/2026/10/12/rollout-2026-10-12T10-00-00-" + "7" * 36 + ".jsonl")
    assert (rollout.family, rollout.conversation_id) == (C.FAMILY_CODEX, "7" * 36)
    assert classify("/x/notes.txt") is None
    marked = []
    observer = observe.Observer(lambda target, trigger: marked.append(target.path) or True)
    assert observer.session_changed(str(main), str(sub)) == 2 and len(marked) == 2
    assert observer.session_changed(str(main), str(sub)) == 0
    (sub / "agent-1.jsonl").write_bytes(b'{"a": 1}\n{"a": 2}\n')
    assert observer.session_changed(str(main), str(sub)) == 1 and marked[-1].endswith("agent-1.jsonl")


def test_nothing_in_src_imports_the_deleted_old_engine():
    import ast
    src = Path(__file__).resolve().parents[2] / "src"
    files = sorted(src.rglob("*.py"))
    assert len(files) > 500
    assert not (src / "core" / "save_pipeline").exists()
    for path in files:
        for node in ast.walk(ast.parse(path.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] + [f"{node.module}.{a.name}" for a in node.names] if isinstance(node, ast.ImportFrom) else []
            assert not any(n.startswith("src.core.save_pipeline") for n in names), (str(path), names)


def test_a_rebuild_refuses_to_swap_while_a_reader_keeps_the_old_wal_busy(tmp_path, monkeypatch):
    from src.core.db import db_path_for
    from src.core.pipeline import rebuild

    monkeypatch.setattr(rebuild, "CHECKPOINT_RETRY_SECONDS", 0.0)
    monkeypatch.setattr(rebuild, "CHECKPOINT_BUSY_SECONDS", 0.05)
    state = tmp_path / "state"
    state.mkdir()
    migrated_connection(state).close()
    plugin = Counting()
    engine = Engine(state, db_path=db_path_for(state), plugins=[plugin.plugin])
    live = plugin_db.db_path(state, plugin.plugin)
    with closing(plugin_db.open_db(state, plugin.plugin)) as conn:
        conn.execute("INSERT INTO settings VALUES ('price', 'v1')")
        conn.commit()
    reader = sqlite3.connect(live, isolation_level=None)
    reader.execute("BEGIN")
    reader.execute("SELECT * FROM settings").fetchall()
    with closing(sqlite3.connect(live)) as writer:
        writer.execute("INSERT INTO settings VALUES ('later', 'v2')")
        writer.commit()
    try:
        with pytest.raises(plugin_db.PluginUnavailable):
            engine.rebuild_plugin("count")
        with closing(sqlite3.connect(live)) as conn:
            assert conn.execute("SELECT COUNT(*) FROM settings").fetchone() == (2,)
    finally:
        reader.close()
