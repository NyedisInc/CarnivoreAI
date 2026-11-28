
from __future__ import annotations

from tests.python.cplugs.save.test_vault_freeze_visible import _freeze, _grow
from src.plugins.save.vault import constants as K
from src.plugins.save.vault import retention
from tests.python.cplugs.save.vault_helpers import CONV, World, jsonl


def _frozen_over_cap_world(tmp_path) -> World:
    world = World(tmp_path)
    world.write_conversation(jsonl(20), subagents=0, tool_results=0)
    world.capture()
    _freeze(world)
    retention.write_state(world.vault.root, {"over_cap": True, "cap_bytes": 1, "history_bytes": 10})
    return world


def _referenced(world: World) -> set:
    return {c.sha256 for pid in world.vault.manifests.point_ids(CONV) for f in world.vault.manifests.read(CONV, pid).files for c in f.chunks}


def test_frozen_and_over_cap_a_growing_transcript_keeps_every_line(tmp_path):
    world = _frozen_over_cap_world(tmp_path)
    statuses = [_grow(world, n) for n in range(4)]
    assert set(statuses) == {"written"}
    newest = world.vault.manifests.newest(CONV)
    main = next(f for f in newest.files if f.role in K.MAIN_ROLES)
    assert main.length == world.transcript().stat().st_size


def test_frozen_a_pure_extension_replaces_the_prior_point(tmp_path):
    world = _frozen_over_cap_world(tmp_path)
    before = world.vault.manifests.point_ids(CONV)
    for n in range(3):
        _grow(world, n)
    after = world.vault.manifests.point_ids(CONV)
    assert len(after) == 1 and after != before


def test_frozen_a_rewritten_transcript_keeps_the_prior_point(tmp_path):
    world = _frozen_over_cap_world(tmp_path)
    first = world.vault.manifests.point_ids(CONV)[0]
    world.transcript().write_bytes(jsonl(25, seed=77))
    assert world.capture(reason="follow").status == "written"
    ids = world.vault.manifests.point_ids(CONV)
    assert first in ids and len(ids) == 2


def test_frozen_a_dropped_file_is_never_superseded(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(20), subagents=1, tool_results=0)
    world.capture()
    _freeze(world)
    prior = world.vault.manifests.newest(CONV)
    extended = [f for f in prior.files if f.role in K.MAIN_ROLES]
    assert not world.vault._only_extends(prior, extended)
    assert world.vault._only_extends(prior, prior.files)


def test_a_frozen_over_cap_capture_leaves_no_orphan_chunks(tmp_path):
    world = _frozen_over_cap_world(tmp_path)
    world.transcript().write_bytes(jsonl(25, seed=5))
    assert world.capture(reason="follow").status == "written"
    stored = {sha for sha, _path in world.vault.blobs.all_blobs()}
    assert stored == _referenced(world)
