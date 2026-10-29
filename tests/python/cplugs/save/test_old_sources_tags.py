
from __future__ import annotations

from pathlib import Path

from src.cplugs.save.vault import adopt, retention
from tests.python.cplugs.save.old_sources_helpers import incoming_point
from tests.python.cplugs.save.vault_helpers import CONV, World, jsonl


def test_a_tagged_point_is_one_point_and_undo_removes_its_marker(tmp_path: Path) -> None:
    world = World(tmp_path)
    tags = {"sources": ["recovered"], "labels": ["junk-20260930:trivial"]}
    log: list = []
    result = adopt.adopt_points(world.vault, [incoming_point(CONV, jsonl(20), tags=tags)], log.append)
    point = result[0].point_id
    manifests = world.vault.manifests
    assert result[0].status == "adopted" and manifests.point_ids(CONV) == [point]
    assert manifests.tags_path(CONV, point).exists() and not manifests.tags_path(CONV, point).name.endswith(".json")
    assert manifests.read_tags(CONV, point) == tags and manifests.is_kept(CONV, point)
    report = retention.collect_garbage(world.vault, grace=0)
    assert report is not None and manifests.read(CONV, point).files
    assert adopt.remove_adopted(world.vault, log)["removed"] == [f"{CONV}/{point}"]
    assert not manifests.tags_path(CONV, point).exists() and not manifests.unit_dir(CONV).exists()
