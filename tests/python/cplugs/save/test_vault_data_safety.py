
from __future__ import annotations

import os
import time
import types

import pytest

from src.cplugs.save.vault import legacy, restore, retention
from src.cplugs.save.vault.ingest import SourceUnstable, ingest_file
from src.cplugs.save.vault.manifest import SoleCopyError
from tests.python.cplugs.save.test_vault_legacy import POINT, SLUG, _old_point
from tests.python.cplugs.save.vault_helpers import CONV, ENC, World, jsonl


def _rewrite(world: World, body: bytes, bump: int) -> None:
    world.transcript().write_bytes(body)
    stamp = time.time() + bump
    os.utime(world.transcript(), (stamp, stamp))


def _bytes_of(world: World, point) -> bytes:
    return b"".join(restore.read_entry(world.vault.blobs, point.main()))


def test_a_shrunk_transcript_leaves_the_good_point_alone_through_thinning_and_the_cap(tmp_path):
    world = World(tmp_path)
    big = jsonl(2000)
    world.write_conversation(big)
    assert world.capture(reason="follow").status == "written"
    good = world.vault.manifests.point_ids(CONV)[0]
    _rewrite(world, jsonl(3, seed=5), 10)
    assert world.capture(reason="follow").status == "written"
    assert world.vault.manifests.is_kept(CONV, good)
    retention.assess(world.vault, cap_bytes=1)
    for i in range(12):
        with open(world.transcript(), "ab") as handle:
            handle.write(jsonl(1, seed=100 + i))
        os.utime(world.transcript(), (time.time() + 20 + i, time.time() + 20 + i))
        assert world.capture(reason="follow").status == "written"
    retention.thin_unit(world.vault, CONV)
    assert good in world.vault.manifests.point_ids(CONV)
    assert _bytes_of(world, world.vault.manifests.read(CONV, good)) == big


def test_a_truncated_to_nothing_transcript_keeps_the_point_before_it(tmp_path):
    world = World(tmp_path)
    big = jsonl(300)
    world.write_conversation(big)
    world.capture()
    good = world.vault.manifests.point_ids(CONV)[0]
    _rewrite(world, b"", 10)
    assert world.capture().status == "written"
    assert world.vault.manifests.is_kept(CONV, good) and _bytes_of(world, world.vault.manifests.read(CONV, good)) == big


def test_an_append_is_not_a_rewrite(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(300))
    world.capture()
    first = world.vault.manifests.point_ids(CONV)[0]
    with open(world.transcript(), "ab") as handle:
        handle.write(jsonl(5, seed=3))
    os.utime(world.transcript(), (time.time() + 5, time.time() + 5))
    assert world.capture().status == "written" and not world.vault.manifests.is_kept(CONV, first)


def test_a_missing_manifests_folder_collects_nothing(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(300))
    world.capture()
    blobs = list(world.vault.blobs.all_blobs())
    assert blobs
    os.rename(world.vault.root / "manifests", world.vault.root / "manifests-away")
    result = retention.collect_garbage(world.vault, grace=0)
    assert result.get("skipped") == 1 and result["removed"] == 0
    assert len(list(world.vault.blobs.all_blobs())) == len(blobs)
    os.rename(world.vault.root / "manifests-away", world.vault.root / "manifests")
    restore.verify_manifest(world.vault.blobs, world.vault.manifests.newest(CONV))


def test_blobs_with_no_manifest_naming_any_chunk_are_not_collected(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(100))
    world.capture()
    for path in (world.vault.root / "manifests" / CONV).glob("*.json"):
        path.unlink()
    result = retention.collect_garbage(world.vault, grace=0)
    assert result.get("skipped") == 1 and list(world.vault.blobs.all_blobs())


def test_an_unreadable_manifest_is_not_a_surviving_copy(tmp_path):
    world = World(tmp_path)
    main = world.write_conversation(jsonl(100))
    world.capture()
    world.grow_history(1)
    a, b = world.vault.manifests.point_ids(CONV)
    (world.vault.root / "manifests" / CONV / f"{a}.json").write_text("{broken")
    with pytest.raises(SoleCopyError):
        world.vault.manifests.delete(CONV, b)
    assert world.vault.manifests.newest(CONV).point_id == b


def test_a_read_that_comes_back_short_is_refused_not_recorded_as_the_whole_file(tmp_path, monkeypatch):
    world = World(tmp_path)
    main = world.write_conversation(jsonl(50), subagents=0, tool_results=0)
    real = os.stat

    def bigger(path, *a, **k):
        st = real(path, *a, **k)
        if str(path) == str(main):
            fields = {n: getattr(st, n) for n in dir(st) if n.startswith("st_")}
            return types.SimpleNamespace(**{**fields, "st_size": st.st_size + 4096})
        return st

    monkeypatch.setattr("src.cplugs.save.vault.ingest.os.stat", bigger)
    with pytest.raises(SourceUnstable):
        ingest_file(world.vault.blobs, main, role="transcript", home="claude", rel=f"projects/{ENC}/{CONV}.jsonl")
    assert world.capture().status == "failed" and world.vault.manifests.point_ids(CONV) == []


def test_a_chunk_reused_by_a_capture_gets_a_fresh_mtime_so_a_collection_grace_protects_it(tmp_path):
    world = World(tmp_path)
    raw = b"a chunk that is already stored\n"
    ref, _size, _new = world.vault.blobs.put(raw)
    path, _codec = world.vault.blobs.find(ref.sha256)
    old = time.time() - 5 * 3600
    os.utime(path, (old, old))
    world.vault.blobs.put(raw)
    assert time.time() - path.stat().st_mtime < 60


def test_blob_folders_are_fsynced_before_the_manifest_that_names_them(tmp_path, monkeypatch):
    from src.cplugs.save.engine import layout
    from src.cplugs.save.vault.manifest import ManifestStore

    world = World(tmp_path)
    world.write_conversation(jsonl(50), subagents=0, tool_results=0)
    events = []
    real_sync, real_write = layout.fsync_path, ManifestStore.write
    monkeypatch.setattr(layout, "fsync_path", lambda p: (events.append(("fsync", str(p))), real_sync(p))[1])
    monkeypatch.setattr(ManifestStore, "write", lambda self, m: (events.append(("manifest", m.point_id)), real_write(self, m))[1])
    assert world.capture().status == "written"
    kinds = [kind for kind, _ in events]
    assert "manifest" in kinds and any(k == "fsync" and "blobs" in v for k, v in events[: kinds.index("manifest")])


def test_two_captures_writing_the_same_new_chunk_at_once_do_not_collide(tmp_path):
    import threading

    world = World(tmp_path)
    raws = [os.urandom(4000) for _ in range(40)]
    errors = []

    def work() -> None:
        try:
            for raw in raws:
                world.vault.blobs.put(raw)
        except OSError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len(list(world.vault.blobs.all_blobs())) == 40


def test_an_old_pin_a_torn_last_line_the_working_dir_and_an_archived_rollout_all_survive_the_migration(tmp_path):
    world = World(tmp_path)
    body = jsonl(40) + b'{"cwd":"/Users/x/proj","partial":"half a li'
    _old_point(world, body)
    (world.state / "time-machine" / SLUG / CONV / POINT / "pinned").write_text("")
    meta = world.state / "time-machine" / SLUG / CONV / POINT / "meta.json"
    import json

    data = json.loads(meta.read_text())
    data.pop("working_dir")
    meta.write_text(json.dumps(data))
    projects = lambda: [{"uid": "uid-1", "root": "/Users/x", "display_name": "x"}]  # noqa: E731
    progress = legacy.migrate(world.vault, world.state, projects=projects)
    assert progress == legacy.LegacyProgress(more=False, failed=0)
    point = world.vault.manifests.newest(CONV)
    assert world.vault.manifests.is_pinned(CONV, point.point_id)
    assert _bytes_of(world, point) == body
    assert point.working_dir == "/Users/x/proj" and point.project_uid == "uid-1"
    assert legacy.codex_rel("/home/u/.codex/archived_sessions/rollout-1-abc.jsonl") == "archived_sessions/rollout-1-abc.jsonl"
    assert legacy.codex_rel("/home/u/.codex/sessions/2026/03/01/rollout-1-abc.jsonl") == "sessions/2026/03/01/rollout-1-abc.jsonl"
