
from __future__ import annotations

import threading
import time
from dataclasses import replace

import pytest
from fastapi import HTTPException

from src.core.pipeline import contract as C
from src.core.pipeline import engine as engine_mod
from src.core.pipeline import observe, reader, runtime, scan
from src.core.pipeline.deliver import FileTarget
from src.core.pipeline.engine import Engine
from tests.pipeline import corpus as K
from tests.pipeline.test_engine import Counting, Fake, drain, make, transcript
from tests.python.federation.test_federation_route_inventory import peer_bearer  # noqa: F401


def _no_download(monkeypatch) -> None:
    monkeypatch.setattr(reader, "request_download", lambda path: True)


def _helpers() -> list:
    return [t for t in threading.enumerate() if t.name == "pipeline-read" and t.is_alive()]


def test_m1_a_stored_off_save_plugin_stops_neither_the_boot_nor_a_lifecycle_trigger(tmp_path, monkeypatch):
    from concurrent.futures import Future

    from src.cplugs.host import runtime as host_runtime, state as owner_state
    from src.core.pipeline import triggers, wiring

    manifest = host_runtime.find("save").manifest
    owner_state.update(tmp_path, manifest, None, lambda st: replace(st, enabled=False))
    assert owner_state.stored_enabled(tmp_path, "save") is False
    started = []
    db = tmp_path / "carnivore.db"
    written = Future()
    written.set_result("written")
    fake = type("FakeEngine", (), {"db_path": db, "write_milestone": lambda self, *a, **k: written})()
    monkeypatch.delenv("CLOUDE_TEST_MODE", raising=False)
    monkeypatch.delenv("CLOUDE_SAVE_PIPELINE", raising=False)
    monkeypatch.setattr(runtime, "start", lambda *a: started.append(a))
    monkeypatch.setattr(runtime, "ensure", lambda *a: fake)
    assert wiring.install() is True and started == [()]
    assert triggers.enqueue("kill", lambda conn: None, state_dir=tmp_path, db_path=db).result(timeout=5).state == "done"


def test_m2_a_plugin_failing_on_a_live_file_does_not_throttle_the_healthy_plugin(tmp_path):
    fake, healthy, poison = Fake(), Counting("healthy"), Counting("poison")
    engine = Engine(tmp_path / "state", plugins=[healthy.plugin, poison.plugin], clock=fake.mono, wall=fake.wall)
    target = transcript(tmp_path / "c", "live.jsonl", 3)
    poison.fail.add(target.path)
    delivered = []
    for step in range(12):
        with open(target.path, "ab") as handle:
            handle.write(K.jl(K.user(100 + step, K.MAIN, 1)))
        engine.mark_dirty(target)
        drain(engine)
        delivered.append(healthy.counts(engine.state_dir)[target.path])
        fake.advance(2.0)
    assert delivered == [4 + i for i in range(12)]
    assert poison.attempts[target.path] == 3
    state = engine.status()["plugins"]
    assert state["poison"]["failures"] == 1 and state["healthy"]["failures"] == 0
    poison.fail.clear()
    fake.advance(60.0)
    assert drain(engine) is None
    assert poison.counts(engine.state_dir)[target.path] == 15 and engine.status()["state"] == "caught_up"


def test_m3_a_hung_read_leaves_one_helper_thread_however_many_retries(tmp_path, monkeypatch):
    _no_download(monkeypatch)
    fake, plugin, engine = make(tmp_path)
    hung = transcript(tmp_path / "c", "hung.jsonl", 4)
    release, reads = threading.Event(), []
    monkeypatch.setattr(C, "READ_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(reader, "read_slice", lambda p, *a: reads.append(p) or (release.wait(10) and b""))
    before = len(_helpers())
    engine.mark_dirty(hung)
    try:
        for _ in range(6):
            drain(engine)
            fake.advance(300.0)
        assert len(reads) == 1 and len(_helpers()) == before + 1
        assert engine.status()["parked_files"] == 1
    finally:
        release.set()
    for _ in range(200):
        if len(_helpers()) == before:
            break
        time.sleep(0.01)


def test_m3_a_batch_of_hung_files_stops_at_its_wall_time_and_loses_nothing(tmp_path, monkeypatch):
    _no_download(monkeypatch)
    plugin = Counting()
    engine = Engine(tmp_path / "state", plugins=[plugin.plugin])
    targets = [transcript(tmp_path / "c", f"h{i}.jsonl", 2) for i in range(10)]
    release, reads = threading.Event(), []
    monkeypatch.setattr(C, "READ_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(engine_mod, "BATCH_WALL_SECONDS", 0.12)
    monkeypatch.setattr(reader, "read_slice", lambda p, *a: reads.append(p) or (release.wait(10) and b""))
    for target in targets:
        engine.mark_dirty(target)
    try:
        engine.step()
        assert 1 <= len(reads) < 10
        assert engine.dirty.size() == 10
    finally:
        release.set()


def test_m3_the_icloud_download_runs_off_the_worker_one_per_path(monkeypatch):
    gate, calls = threading.Event(), []

    def slow_brctl(argv, **kw):
        calls.append(argv)
        gate.wait(10)
        return type("Done", (), {"returncode": 0})()

    monkeypatch.setattr(reader.subprocess, "run", slow_brctl)
    threading.Timer(1.5, gate.set).start()
    started = time.monotonic()
    first = reader.request_download("/x/placeholder.jsonl")
    second = reader.request_download("/x/placeholder.jsonl")
    assert time.monotonic() - started < 0.5
    assert first is True and second is False
    gate.set()
    for _ in range(200):
        if not reader._downloading:
            break
        time.sleep(0.01)
    assert len(calls) == 1 and calls[0][:2] == ["brctl", "download"]


def test_m3_deep_search_reads_its_index_gap_under_the_wall_time_guard(tmp_path, monkeypatch):
    from src.core.deepsearch import pipeline_plugin
    from src.core.deepsearch.live import range_rows

    release = threading.Event()

    class Hanging:

        end_offset = 0

        def __init__(self, path, start, end) -> None:
            pass

        def __iter__(self):
            release.wait(10)
            return iter(())

    monkeypatch.setattr(range_rows, "RangeReader", Hanging)
    monkeypatch.setattr(C, "READ_TIMEOUT_SECONDS", 0.05)
    threading.Timer(1.5, release.set).start()
    try:
        with pytest.raises(reader.ReadTimeout):
            pipeline_plugin._read_lines(str(tmp_path / "a.jsonl"), 0, 100, 0, {}, C.FAMILY_CLAUDE)
    finally:
        release.set()


def test_m4_live_keys_are_taken_before_a_replay_and_a_live_mark_promotes_a_bulk_key(tmp_path):
    fake = Fake()
    dirty = observe.DirtySet(fake.mono)
    bulk = [FileTarget(f"/t/bulk{i}.jsonl", f"b{i}", C.FAMILY_CLAUDE, C.FILE_CONVERSATION) for i in range(50)]
    live = FileTarget("/t/live.jsonl", "live", C.FAMILY_CLAUDE, C.FILE_CONVERSATION)
    promoted = bulk[7]
    for target in bulk:
        dirty.mark_file(target, observe.TRIGGER_REBUILD)
    dirty.mark_file(live, observe.TRIGGER_LIVE)
    assert dirty.mark_file(promoted, observe.TRIGGER_LIVE) is True
    first = [e.key[1] for e in dirty.take(2)]
    assert sorted(first) == sorted([live.path, promoted.path])
    assert len(dirty.take(100)) == 49 and dirty.size() == 0


def test_m4_the_worker_delivers_a_live_file_in_the_first_batch_of_a_replay(tmp_path, monkeypatch):
    fake, plugin, engine = make(tmp_path)
    monkeypatch.setattr(engine_mod, "BATCH_KEYS", 3)
    replay = [transcript(tmp_path / "c", f"r{i}.jsonl", 2) for i in range(10)]
    live = transcript(tmp_path / "c", "live.jsonl", 2)
    for target in replay:
        engine.mark_dirty(target, observe.TRIGGER_SCAN)
    engine.mark_dirty(live)
    engine.step()
    assert plugin.counts(engine.state_dir).get(live.path) == 2
    assert len(plugin.counts(engine.state_dir)) == 3


def test_m4_a_plugin_never_opens_a_file_kind_it_does_not_read(tmp_path, monkeypatch):
    from src.core.deepsearch import constants as dp_constants
    from src.core.deepsearch.pipeline_plugin import DEEPSEARCH
    from src.core.transcript_manifest import constants as TM

    monkeypatch.setattr(dp_constants, "INDEX_SCOPE", "human")
    assert DEEPSEARCH.file_kinds_fn() == {C.FILE_CONVERSATION}
    assert DEEPSEARCH.reads(C.FAMILY_CLAUDE, C.FILE_CONVERSATION) and not DEEPSEARCH.reads(C.FAMILY_CLAUDE, C.FILE_SUBAGENT)
    sub = scan.ManifestFile("/p/c/subagents/a.jsonl", "c", C.FAMILY_CLAUDE, TM.KIND_SUBAGENT, False, False, 90)
    main = scan.ManifestFile("/p/c.jsonl", "c", C.FAMILY_CLAUDE, TM.KIND_CONVERSATION, False, False, 90)
    assert scan.behind(DEEPSEARCH, [sub, main], {}, set()) == [main]

    opened = []
    real = reader.read_slice
    monkeypatch.setattr(reader, "read_slice", lambda p, *a: opened.append(p) or real(p, *a))
    fake, only_conversations, engine = make(tmp_path)
    narrowed = replace(only_conversations.plugin, file_kinds=frozenset({C.FILE_CONVERSATION}))
    wide = Counting("wide")
    engine = Engine(tmp_path / "state2", plugins=[narrowed], clock=fake.mono, wall=fake.wall)
    main_t = transcript(tmp_path / "c", "main.jsonl", 2)
    sub_path = tmp_path / "c" / "main" / "subagents" / "agent-1.jsonl"
    sub_path.parent.mkdir(parents=True)
    sub_path.write_bytes(K.jl(K.user(1, K.MAIN, 1)))
    sub_t = FileTarget(str(sub_path), "main", C.FAMILY_CLAUDE, C.FILE_SUBAGENT)
    both = Engine(tmp_path / "state3", plugins=[wide.plugin], clock=fake.mono, wall=fake.wall)
    for eng in (engine, both):
        eng.mark_dirty(main_t)
        eng.mark_dirty(sub_t)
        drain(eng)
    assert str(sub_path) in wide.counts(both.state_dir)
    narrow_reads = [p for p in opened if p == str(sub_path)]
    assert len(narrow_reads) == 1
    assert main_t.path in only_conversations.counts(engine.state_dir)


def test_m5_no_switch_and_no_grant_stand_in_the_way_but_the_three_pack_rules_hold(
        tmp_path, monkeypatch, peer_bearer):  # noqa: F811
    from contextlib import closing

    from fastapi.testclient import TestClient

    from src.api import deepsearch_peer_routes
    from src.config import settings as app_settings
    from src.core.computers import store as link_store
    from src.core.db import connect, db_path_for
    from src.core.deepsearch.cache import flip
    from src.core.deepsearch.reader import ConversationIndex
    from src.main import app

    calls = []

    async def local(self, q, **kw):
        calls.append(kw)
        hit = {"line": 1, "kind": "user", "snippet": "the flux capacitor", "score": 1.0, "file_kind": "conversation"}
        group = {"conversation_id": "open-1", "matches": 1, "by_kind": {"user": 1}, "by_file_kind": {"conversation": 1},
                 "session_uuid": None, "session": "s", "project_id": None, "project": "open", "first_prompt": "hi",
                 "working_dir": "/work/open/sub", "last_active": "2026-10-12", "family": "claude", "hits": [hit]}
        return {"query": q, "total_conversations": 1, "total_matches": 1, "groups": [group]}

    monkeypatch.setattr(app_settings, "state_dir_override", str(tmp_path))
    monkeypatch.setattr(ConversationIndex, "search", local)
    monkeypatch.setattr(flip, "state", lambda _d: "ready")
    client = TestClient(app, raise_server_exceptions=False)
    ask = lambda: client.get("/api/v1/deepsearch/peer-search", params={"q": "flux"},  # noqa: E731
                             headers={"Authorization": f"Bearer {peer_bearer}"})
    served = ask()
    assert served.status_code == 200, served.text
    body = served.json()
    assert [g["conversation_id"] for g in body["groups"]] == ["open-1"]
    assert calls and all(kw["peers"] is False for kw in calls)
    assert all(kw["for_peer"] is True for kw in calls)
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        link_store.set_direction(conn, "iid-peer", False)
        conn.commit()
    refused = ask()
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "computer_one_way"
    assert len(calls) == 1
