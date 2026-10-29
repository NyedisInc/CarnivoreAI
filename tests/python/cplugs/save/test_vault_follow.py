
from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import List

from src.cplugs.save.vault import follow, health, restore, units
from src.cplugs.save.vault.follow import Engine
from src.cplugs.sdk.blob_codec import Throttle
from tests.python.cplugs.save.vault_helpers import CODEX_ID, CONV, ENC, World, jsonl

IDS = [f"{n:08d}-aaaa-bbbb-cccc-1234567890ab" for n in range(1, 6)]


def engine_for(world: World, rows=None, side_dbs=None, throttle=None, clock=time.time) -> Engine:
    return Engine(lambda: world.vault, world.state, lambda: world.sources, rows=rows, side_dbs=side_dbs,
                  throttle=throttle or Throttle(sleep=lambda s: None), clock=clock)


def drain(engine: Engine, limit: int = 50) -> List[follow.SliceResult]:
    results = []
    for _ in range(limit):
        results.append(engine.run_slice())
        if not results[-1].more:
            return results
    raise AssertionError("the engine never finished")


def rows_of(world: World) -> List[dict]:
    out = []
    for plan in units.scan_claude(world.sources).values():
        for f in plan.files:
            if f.role in ("transcript", "subagent"):
                st = f.path.stat()
                out.append({"path": str(f.path), "family": "claude", "kind": "conversation" if f.role == "transcript" else "subagent",
                            "conversation_id": plan.conversation_id, "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                            "status": "present", "dataless": 0, "gone_at": None})
    return out


def test_enabling_backfills_every_conversation_in_bounded_slices(tmp_path):
    world = World(tmp_path)
    for conv in IDS:
        world.write_conversation(jsonl(60), conv=conv)
    world.write_codex(jsonl(10))
    engine = engine_for(world, throttle=Throttle(slice_seconds=0, sleep=lambda s: None))
    engine.run_slice()
    midway = health.read(world.state)
    assert midway["on_disk"] == 6 and midway["uncovered"] >= 5 and midway["uncovered_since"]
    results = [None, *drain(engine, limit=400)]
    assert len(results) >= 6
    assert sorted(world.vault.manifests.units()) == sorted([*IDS, CODEX_ID])
    record = health.read(world.state)
    assert record["on_disk"] == 6 and record["uncovered"] == 0 and record["uncovered_since"] is None and record["swept_at"]
    assert health.evaluate(record)["known"] is True
    assert all(world.vault.manifests.newest(u).reason == "backfill" for u in IDS)
    engine.run_slice()
    assert sum(r.captured for r in drain(engine)) == 0


def test_the_follow_catches_a_write_made_while_the_server_was_down(tmp_path):
    world = World(tmp_path)
    main = world.write_conversation(jsonl(60))
    drain(engine_for(world))
    assert len(world.vault.manifests.point_ids(CONV)) == 1
    with open(main, "ab") as handle:
        handle.write(jsonl(5, seed=3))
    os.utime(main, (time.time() - 10 * 24 * 3600, time.time() - 10 * 24 * 3600))
    restarted = engine_for(world)
    results = drain(restarted)
    assert sum(r.captured for r in results) == 1 and len(world.vault.manifests.point_ids(CONV)) == 1
    newest = world.vault.manifests.newest(CONV)
    assert b"".join(restore.read_entry(world.vault.blobs, newest.main())) == main.read_bytes()


def test_a_touched_but_identical_file_is_checked_once_not_forever(tmp_path):
    world = World(tmp_path)
    main = world.write_conversation(jsonl(60))
    feed = {"rows": rows_of(world)}
    engine = engine_for(world, rows=lambda: feed["rows"])
    drain(engine)
    later = time.time() - 3600
    os.utime(main, (later, later))
    feed["rows"] = rows_of(world)
    captures = []
    real = world.vault.capture
    world.vault.capture = lambda *a, **k: (captures.append(a[0].unit), real(*a, **k))[1]
    try:
        engine._swept_at = time.time()
        drain(engine)
        assert captures == [CONV] and len(world.vault.manifests.point_ids(CONV)) == 1
        for _ in range(3):
            drain(engine)
            engine._sweep(world.vault, world.sources, time.time())
            drain(engine)
        assert captures == [CONV]
        with open(main, "ab") as handle:
            handle.write(jsonl(4, seed=8))
        feed["rows"] = rows_of(world)
        drain(engine)
        assert captures == [CONV, CONV] and len(world.vault.manifests.point_ids(CONV)) == 1
    finally:
        world.vault.capture = real


def test_the_follow_uses_the_transcript_manifest_states(tmp_path):
    world = World(tmp_path)
    main = world.write_conversation(jsonl(60))
    feed = {"rows": rows_of(world)}
    engine = engine_for(world, rows=lambda: feed["rows"])
    drain(engine)
    assert len(world.vault.manifests.point_ids(CONV)) == 1
    engine._swept_at = time.time()
    assert drain(engine)[-1].captured == 0
    with open(main, "ab") as handle:
        handle.write(jsonl(4, seed=8))
    feed["rows"] = [{**r, "status": "grown", "size": main.stat().st_size, "mtime_ns": main.stat().st_mtime_ns}
                    if r["path"] == str(main) else r for r in rows_of(world)]
    assert sum(r.captured for r in drain(engine)) == 1 and len(world.vault.manifests.point_ids(CONV)) == 1


def test_a_gone_original_is_not_recaptured_and_keeps_its_last_point(tmp_path):
    world = World(tmp_path)
    main = world.write_conversation(jsonl(60))
    feed = {"rows": rows_of(world)}
    engine = engine_for(world, rows=lambda: feed["rows"])
    drain(engine)
    body = main.read_bytes()
    main.unlink()
    feed["rows"] = [{**r, "status": "gone", "gone_at": "2026-10-16T00:00:00Z"} for r in feed["rows"]]
    engine._swept_at = time.time()
    drain(engine)
    newest = world.vault.manifests.newest(CONV)
    assert len(world.vault.manifests.point_ids(CONV)) == 1
    assert b"".join(restore.read_entry(world.vault.blobs, newest.main())) == body


def test_the_throttle_rests_in_proportion_to_the_work():
    slept: List[float] = []
    t = Throttle(duty=0.25, sleep=slept.append)
    t.rest(0.2)
    t.rest(0.1)
    assert [round(x, 6) for x in slept] == [0.6, 0.3]
    assert t.rested == sum(slept)


def test_a_codex_rollout_round_trips_and_nothing_else_of_codex_is_read(tmp_path):
    world = World(tmp_path)
    rollout = world.write_codex(jsonl(80))
    (world.codex / "auth.json").write_text('{"token":"secret"}')
    (world.codex / "state_5.sqlite").write_bytes(os.urandom(100))
    (world.codex / "sessions" / "notes.txt").write_text("not a rollout")
    drain(engine_for(world))
    assert world.vault.manifests.units() == [CODEX_ID]
    manifest = world.vault.manifests.newest(CODEX_ID)
    assert [f.role for f in manifest.files] == ["codex_rollout"] and manifest.family == "codex"
    out = tmp_path / "restored"
    restore.restore_to_root(world.vault.blobs, manifest, out)
    assert (out / "codex" / manifest.files[0].rel).read_bytes() == rollout.read_bytes()
    assert not [p for p in (world.state / "vault").rglob("*") if p.is_file() and b"secret" in p.read_bytes()]


def test_a_side_database_copy_is_consistent_while_a_writer_is_active(tmp_path):
    world = World(tmp_path)
    db = world.state / "bookmarks.db"
    writer = sqlite3.connect(db, isolation_level=None)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("CREATE TABLE a (id INTEGER PRIMARY KEY, n INTEGER)")
    writer.execute("CREATE TABLE b (id INTEGER PRIMARY KEY, n INTEGER)")
    writer.execute("INSERT INTO a VALUES (1, 0)")
    writer.execute("INSERT INTO b VALUES (1, 0)")
    for _ in range(200):
        writer.execute("BEGIN")
        writer.execute("UPDATE a SET n = n + 1")
        writer.execute("UPDATE b SET n = n + 1")
        writer.execute("COMMIT")
    committed_before = 200
    raw = tmp_path / "raw.db"
    raw.write_bytes(db.read_bytes())
    try:
        raw_n = sqlite3.connect(raw).execute("SELECT n FROM a").fetchone()[0]
    except sqlite3.OperationalError:
        raw_n = 0
    assert raw_n < committed_before
    stop = threading.Event()

    def keep_writing() -> None:
        own = sqlite3.connect(db, isolation_level=None, timeout=30)
        own.execute("PRAGMA wal_autocheckpoint=0")
        while not stop.is_set():
            own.execute("BEGIN")
            own.execute("UPDATE a SET n = n + 1")
            own.execute("UPDATE b SET n = n + 1")
            own.execute("COMMIT")
        own.close()

    thread = threading.Thread(target=keep_writing)
    thread.start()
    try:
        outcome = world.vault.capture_side_databases(world.state, [("bookmarks.db", db)])
    finally:
        stop.set()
        thread.join()
    assert outcome.status == "written"
    manifest = world.vault.manifests.newest("side-databases")
    out = tmp_path / "restored"
    restore.restore_to_root(world.vault.blobs, manifest, out)
    copy = sqlite3.connect(out / "state" / "bookmarks.db")
    a, b = copy.execute("SELECT n FROM a").fetchone()[0], copy.execute("SELECT n FROM b").fetchone()[0]
    assert copy.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert a == b and a >= committed_before


def test_the_engine_over_the_cap_reports_it_loudly_deletes_nothing_and_still_captures(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(300))
    world.capture()
    world.side_history(3)
    before = world.vault.manifests.point_ids("side-databases")
    engine = Engine(lambda: world.vault, world.state, lambda: world.sources, cap_bytes=lambda: 1,
                    throttle=Throttle(sleep=lambda s: None), clock=lambda: time.time() + 4 * 3600)
    with open(world.transcript(), "ab") as handle:
        handle.write(jsonl(5, seed=99))
    os.utime(world.transcript(), (time.time() + 50, time.time() + 50))
    drain(engine)
    record = health.read(world.state)
    assert record["over_cap"] is True and health.evaluate(record)["over_cap"] is True
    after = world.vault.manifests.point_ids("side-databases")
    assert set(before) <= set(after)
    newest = world.vault.manifests.newest(CONV)
    assert b"".join(restore.read_entry(world.vault.blobs, newest.main())) == world.transcript().read_bytes()
    for point in world.vault.manifests.points(CONV):
        restore.verify_manifest(world.vault.blobs, point)
