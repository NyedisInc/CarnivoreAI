
from __future__ import annotations

import os
import threading
import time

import pytest

from src.cplugs.save.vault import restore, retention
from src.cplugs.save.vault.manifest import SoleCopyError
from tests.python.cplugs.save.vault_helpers import CONV, ENC, World, jsonl

OTHER = "5440f51e-018d-47a4-8fdf-c52dbf80f162"


def _many_points(world: World, count: int, conv: str = CONV, reason: str = "follow") -> None:
    world.grow_history(count, conv, reason)


def test_a_sole_copy_survives_a_cap_far_below_its_size(tmp_path):
    world = World(tmp_path)
    for conv in (CONV, OTHER):
        world.write_conversation(jsonl(400), conv=conv)
        world.capture(conv)
    state = retention.assess(world.vault, cap_bytes=1)
    assert state["history_bytes"] == 0 and state["over_cap"] is False
    for conv in (CONV, OTHER):
        assert len(world.vault.manifests.point_ids(conv)) == 1
        restore.verify_manifest(world.vault.blobs, world.vault.manifests.newest(conv))
    retention.collect_garbage(world.vault, grace=0)
    for conv in (CONV, OTHER):
        restore.verify_manifest(world.vault.blobs, world.vault.manifests.newest(conv))
    with pytest.raises(SoleCopyError):
        world.vault.manifests.delete(CONV, world.vault.manifests.point_ids(CONV)[0])


def test_over_the_cap_the_live_file_is_still_captured_and_nothing_is_deleted(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(300))
    world.capture()
    world.side_history(4)
    side_before = world.vault.manifests.point_ids("side-databases")
    state = retention.assess(world.vault, cap_bytes=1)
    assert state["over_cap"] is True and state["history_bytes"] > 1
    assert world.vault.manifests.point_ids("side-databases") == side_before
    before = world.vault.manifests.point_ids(CONV)
    with open(world.transcript(), "ab") as handle:
        handle.write(jsonl(5, seed=77))
    outcome = world.capture(reason="follow")
    after = world.vault.manifests.point_ids(CONV)
    assert outcome.status == "written" and outcome.point_id == after[-1] and len(after) == len(before)
    newest = world.vault.manifests.newest(CONV)
    assert b"".join(restore.read_entry(world.vault.blobs, newest.main())) == world.transcript().read_bytes()
    with open(world.transcript(), "ab") as handle:
        handle.write(jsonl(5, seed=78))
    world.vault.manifests.set_pinned(CONV, after[-1], True)
    again = world.capture(reason="follow")
    assert again.status == "written" and after[-1] in world.vault.manifests.point_ids(CONV)
    assert retention.read_state(world.vault.root)["over_cap"] is True


def test_over_the_cap_a_plain_follow_point_is_replaced_not_added(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(300))
    _many_points(world, 3, reason="kill")
    assert world.capture(reason="follow").status in ("written", "unchanged")
    with open(world.transcript(), "ab") as handle:
        handle.write(jsonl(2, seed=1))
    os.utime(world.transcript(), (time.time() + 100, time.time() + 100))
    assert world.capture(reason="follow").status == "written"
    retention.assess(world.vault, cap_bytes=1)
    ids = world.vault.manifests.point_ids(CONV)
    with open(world.transcript(), "ab") as handle:
        handle.write(jsonl(2, seed=2))
    os.utime(world.transcript(), (time.time() + 200, time.time() + 200))
    outcome = world.capture(reason="follow")
    after = world.vault.manifests.point_ids(CONV)
    assert outcome.status == "written" and len(after) == len(ids)
    assert after[-1] == outcome.point_id and ids[-1] not in after
    newest = world.vault.manifests.newest(CONV)
    assert b"".join(restore.read_entry(world.vault.blobs, newest.main())) == world.transcript().read_bytes()


def test_a_unit_whose_original_is_gone_keeps_every_point(tmp_path):
    world = World(tmp_path)
    main = world.write_conversation(jsonl(50))
    _many_points(world, 12)
    assert len(world.vault.manifests.point_ids(CONV)) == 12
    main.unlink()
    assert retention.thin_unit(world.vault, CONV) == []
    assert len(world.vault.manifests.point_ids(CONV)) == 12
    retention.assess(world.vault, cap_bytes=1)
    assert len(world.vault.manifests.point_ids(CONV)) == 12
    restore.verify_manifest(world.vault.blobs, world.vault.manifests.newest(CONV))


def test_a_present_original_is_thinned_to_one_point_but_never_below_one(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(50))
    _many_points(world, 12)
    dropped = retention.thin_unit(world.vault, CONV)
    assert len(dropped) == 11 and len(world.vault.manifests.point_ids(CONV)) == 1
    assert world.vault.manifests.newest(CONV).raw_bytes() == world.transcript().stat().st_size + sum(
        f.length for f in world.vault.manifests.newest(CONV).files if f.role != "transcript")


def test_a_pinned_point_is_never_dropped(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(50))
    _many_points(world, 12)
    first = world.vault.manifests.point_ids(CONV)[0]
    world.vault.manifests.set_pinned(CONV, first, True)
    retention.thin_unit(world.vault, CONV)
    assert first in world.vault.manifests.point_ids(CONV)


def test_collection_removes_only_unreferenced_old_chunks_and_stops_on_doubt(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(50))
    world.capture()
    stray, _size, _new = world.vault.blobs.put(b"nobody references me\n")
    path, _codec = world.vault.blobs.find(stray.sha256)
    old = time.time() - 10 * 24 * 3600
    os.utime(path, (old, old))
    (world.vault.root / "manifests" / CONV / "20200101T000000Z-follow.json").write_text("{not json")
    assert retention.collect_garbage(world.vault).get("skipped") == 1 and path.exists()
    (world.vault.root / "manifests" / CONV / "20200101T000000Z-follow.json").unlink()
    result = retention.collect_garbage(world.vault)
    assert result["removed"] == 1 and not path.exists()
    restore.verify_manifest(world.vault.blobs, world.vault.manifests.newest(CONV))


def test_a_capture_that_cannot_read_the_main_file_leaves_the_old_point_untouched(tmp_path, monkeypatch):
    world = World(tmp_path)
    main = world.write_conversation(jsonl(50))
    world.capture()
    old_ids = world.vault.manifests.point_ids(CONV)
    with open(main, "ab") as handle:
        handle.write(jsonl(3))
    monkeypatch.setattr("src.cplugs.save.vault.ingest.dataless.is_dataless_file", lambda p: p == main)
    outcome = world.capture()
    assert outcome.status == "failed" and world.vault.manifests.point_ids(CONV) == old_ids
    restore.verify_manifest(world.vault.blobs, world.vault.manifests.newest(CONV))


def test_an_assessment_that_queued_behind_another_judges_by_the_cap_in_force_when_it_runs(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(50), conv=CONV)
    world.capture(CONV)
    _many_points(world, 2)
    cap = {"bytes": 1}
    queued = threading.Thread(target=retention.assess, args=(world.vault, lambda: cap["bytes"]))
    with retention._ASSESS_LOCK:
        queued.start()
        cap["bytes"] = 10 ** 9
    queued.join(timeout=30)
    state = retention.read_state(world.vault.root)
    assert not queued.is_alive() and state["cap_bytes"] == 10 ** 9 and state["over_cap"] is False


def test_a_moved_folder_stale_transcript_path_does_not_protect_follow_points(tmp_path):
    import json

    world = World(tmp_path)
    world.write_conversation(jsonl(60))
    _many_points(world, 14)
    store = world.vault.manifests
    for point_id in store.point_ids(CONV):
        path = store.unit_dir(CONV) / f"{point_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        main = next(f for f in data["files"] if f["role"] == "transcript")
        data["files"].insert(0, {**main, "source_path": str(tmp_path / "old-folder" / "gone.jsonl")})
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(temp, path)
    state = retention.assess(world.vault, cap_bytes=1 << 40)
    assert state["protected_units"] == 0
    assert len(store.point_ids(CONV)) == 1
