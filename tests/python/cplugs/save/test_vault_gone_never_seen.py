
from __future__ import annotations

import json

from src.plugins.save.vault import constants as K
from src.plugins.save.vault import gone_watch, retention
from tests.python.cplugs.save.test_vault_mass_gone_freeze import NOW, _conv
from tests.python.cplugs.save.vault_helpers import World, jsonl

COUNT = 12


def _capture(world: World, first: int, last: int, reason: str = K.REASON_FOLLOW) -> None:
    for i in range(first, last):
        world.write_conversation(jsonl(5, seed=i), conv=_conv(i), enc=f"-proj-{i}", subagents=0, tool_results=0)
        world.capture(conv=_conv(i), reason=reason)


def _remove(world: World, first: int, last: int) -> None:
    for i in range(first, last):
        world.transcript(_conv(i), f"-proj-{i}").unlink()


def _baseline(world: World) -> None:
    _capture(world, 0, 1)
    retention.assess(world.vault, now=NOW)


def test_import_only_units_never_count_and_do_not_freeze(tmp_path):
    world = World(tmp_path)
    _baseline(world)
    _capture(world, 1, 1 + COUNT, K.REASON_IMPORT)
    _remove(world, 1, 1 + COUNT)
    assert retention.assess(world.vault, now=NOW + 60)["mass_gone"] is None
    assert gone_watch.frozen(world.vault.root) is None


def test_units_captured_and_deleted_inside_one_pass_count(tmp_path):
    world = World(tmp_path)
    _baseline(world)
    _capture(world, 1, 1 + COUNT)
    _remove(world, 1, 1 + COUNT)
    report = retention.assess(world.vault, now=NOW + 60)["mass_gone"]
    assert report and report["count"] == COUNT
    assert gone_watch.frozen(world.vault.root) is not None


def test_an_imported_unit_later_captured_from_disk_then_vanishing_counts(tmp_path):
    world = World(tmp_path)
    _baseline(world)
    _capture(world, 1, 1 + COUNT, K.REASON_IMPORT)
    _remove(world, 1, 1 + COUNT)
    assert retention.assess(world.vault, now=NOW + 60)["mass_gone"] is None
    _capture(world, 1, 1 + COUNT)
    assert retention.assess(world.vault, now=NOW + 120)["mass_gone"] is None
    _remove(world, 1, 1 + COUNT)
    report = retention.assess(world.vault, now=NOW + 180)["mass_gone"]
    assert report and report["count"] == COUNT


def test_a_legacy_memory_file_does_not_realarm_on_units_already_gone(tmp_path):
    world = World(tmp_path)
    _capture(world, 0, COUNT)
    _remove(world, 0, COUNT)
    units = sorted(world.vault.manifests.units())
    (world.vault.root / K.GONE_FILE).write_text(json.dumps({"gone": units, "events": [], "level": 0, "step": 0}), encoding="utf-8")
    assert retention.assess(world.vault, now=NOW + 60)["mass_gone"] is None
    assert gone_watch.frozen(world.vault.root) is None


def test_a_crate_adoption_of_units_with_no_originals_raises_nothing(tmp_path):
    from src.plugins.save.vault import adopt
    from tests.python.cplugs.save.test_vault_adopt import incoming

    source, target = World(tmp_path / "sender"), World(tmp_path / "receiver")
    _baseline(target)
    for i in range(1, 1 + COUNT):
        _capture(source, i, i + 1)
    points = [p for i in range(1, 1 + COUNT) for p in incoming(source, conv=_conv(i))]
    adopt.adopt_points(target.vault, points, lambda e: None)
    assert retention.assess(target.vault, now=NOW + 60)["mass_gone"] is None
    assert gone_watch.frozen(target.vault.root) is None
    adopted = target.vault.manifests.points(_conv(1))[0]
    assert adopted.reason == K.REASON_ADOPT
    assert target.vault.manifests.read_tags(_conv(1), adopted.point_id)["sender_reason"] == K.REASON_FOLLOW
