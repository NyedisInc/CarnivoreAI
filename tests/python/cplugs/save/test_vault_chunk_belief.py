
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.cplugs.save.vault import adopt, restore
from src.cplugs.save.vault.store import STATUS_FAILED, STATUS_PARTIAL, STATUS_WRITTEN
from tests.python.cplugs.save.vault_helpers import CONV, World, jsonl

BIG = 20_000


class StopAfterFirstChunk:

    def rest(self, worked: float) -> None:
        pass

    def expired(self) -> bool:
        return True


def parked_world(tmp_path: Path):
    world = World(tmp_path)
    other = "99999999-aaaa-bbbb-cccc-1234567890ab"
    world.write_conversation(jsonl(5), conv=other, subagents=0, tool_results=0)
    assert world.capture(other).status == STATUS_WRITTEN
    world.write_conversation(jsonl(BIG), subagents=0, tool_results=0)
    outcome = world.capture(pace=StopAfterFirstChunk())
    assert outcome.status == STATUS_PARTIAL
    parked = world.vault.partials[str(world.transcript())]
    return world, parked.refs[0].sha256


def test_an_undone_import_does_not_leave_a_parked_read_trusting_the_chunk_it_removed(tmp_path):
    world, sha = parked_world(tmp_path)
    undo = [{"unit": "imported-unit", "point_id": "20260101T000000Z-import-0001", "manifest_sha256": "0" * 64, "new_chunks": [sha]}]
    report = adopt.remove_adopted(world.vault, undo)
    assert world.vault.blobs.find(sha) is None and not report["errors"]
    outcome = world.capture()
    assert outcome.status == STATUS_WRITTEN
    assert world.vault.blobs.find(sha) is not None
    restore.verify_manifest(world.vault.blobs, world.vault.manifests.newest(CONV))


@pytest.mark.parametrize("how", ["parked", "prior"])
def test_a_chunk_deleted_by_hand_is_caught_before_a_point_names_it(tmp_path, how):
    if how == "parked":
        world, sha = parked_world(tmp_path)
    else:
        world = World(tmp_path)
        world.write_conversation(jsonl(BIG), subagents=0, tool_results=0)
        assert world.capture().status == STATUS_WRITTEN
        sha = world.vault.manifests.newest(CONV).main().chunks[0].sha256
        with open(world.transcript(), "ab") as handle:
            handle.write(jsonl(5, seed=7))
    world.vault.blobs.find(sha)[0].unlink()
    outcome = world.capture()
    assert outcome.status == STATUS_FAILED and "missing" in outcome.detail
    assert len(world.vault.manifests.point_ids(CONV)) == (0 if how == "parked" else 1)


def test_the_checks_before_publishing_ask_the_disk_not_the_memory(tmp_path):
    world = World(tmp_path)
    ref, _size, _new = world.vault.blobs.put(b"remembered\n")
    assert world.vault.blobs.has(ref.sha256) and world.vault.blobs.on_disk(ref.sha256)
    world.vault.blobs.find(ref.sha256)[0].unlink()
    assert world.vault.blobs.has(ref.sha256)
    assert not world.vault.blobs.on_disk(ref.sha256)


def test_remove_unlinks_and_forgets_in_one_call(tmp_path):
    world = World(tmp_path)
    ref, _size, _new = world.vault.blobs.put(b"to be removed\n")
    assert world.vault.blobs.has(ref.sha256)
    assert world.vault.blobs.remove(ref.sha256) > 0
    assert not world.vault.blobs.has(ref.sha256) and world.vault.blobs.find(ref.sha256) is None
    assert world.vault.blobs.remove(ref.sha256) == 0


def test_a_different_volume_at_the_same_path_does_not_inherit_the_belief(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(300), subagents=0, tool_results=0)
    assert world.capture().status == STATUS_WRITTEN
    blobs = world.state / "vault" / "blobs"
    os.rename(blobs, world.state / "vault" / "blobs-old-drive")
    blobs.mkdir()
    with open(world.transcript(), "ab") as handle:
        handle.write(jsonl(3, seed=5))
    assert world.capture().status == STATUS_WRITTEN
    restore.verify_manifest(world.vault.blobs, world.vault.manifests.newest(CONV))
