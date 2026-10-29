
from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path
from typing import Any, Dict, List

from src.cplugs.save.fallback import BackupTranscripts
from src.cplugs.save.vault import adopt, retention
from src.cplugs.save.vault.ranges import EntryReader
from src.core.deepsearch.fallback_hook import FallbackPoint, IncomingFile
from tests.python.cplugs.save.vault_helpers import CONV, World, jsonl


def two_points(world: World) -> None:
    world.write_conversation(jsonl(300))
    assert world.capture(reason="kill").status == "written"
    world.grow_history(1, seeds=[5])


def incoming(source: World, rel_map=None) -> List[FallbackPoint]:
    points = BackupTranscripts(vault=lambda: source.vault).list_points(CONV)
    out = []
    for point in points:
        manifest = source.vault.manifests.read(CONV, point.point_id)
        files = []
        for pf, entry in zip(point.files, manifest.files):
            raw = b"".join(source.vault.blobs.get(c) for c in entry.chunks)
            reader = EntryReader(source.vault.blobs, entry)
            files.append(IncomingFile(role=pf.role, home=pf.home, rel=(rel_map or (lambda r: r))(pf.rel), source_path=pf.source_path,
                                      length=pf.length, sha256=hashlib.sha256(raw).hexdigest(), mode=pf.mode, mtime_ns=pf.mtime_ns,
                                      lines=pf.lines, read=lambda r=reader, n=pf.length: iter([r.read(0, n)])))
        out.append(dataclasses.replace(point, files=tuple(files)))
    return out


def listing(world: World) -> Dict[str, Any]:
    return {m.point_id: m.as_json() for m in world.vault.manifests.points(CONV)}


def test_round_trip_every_chunk_verifies(tmp_path: Path) -> None:
    source, target = World(tmp_path / "a"), World(tmp_path / "b")
    two_points(source)
    log: List[dict] = []
    result = adopt.adopt_points(target.vault, incoming(source), log.append)
    assert [r.status for r in result] == ["adopted", "adopted"] and len(log) == 2
    assert set(listing(target)) == set(listing(source))
    for manifest in target.vault.manifests.points(CONV):
        for entry in manifest.files:
            raw = b"".join(target.vault.blobs.get(c) for c in entry.chunks)
            assert len(raw) == entry.length
            assert hashlib.sha256(raw).hexdigest() == hashlib.sha256(
                b"".join(source.vault.blobs.get(c) for c in source.vault.manifests.read(CONV, manifest.point_id).files[manifest.files.index(entry)].chunks)).hexdigest()


def test_the_same_points_twice_are_one_point(tmp_path: Path) -> None:
    source, target = World(tmp_path / "a"), World(tmp_path / "b")
    two_points(source)
    adopt.adopt_points(target.vault, incoming(source), lambda e: None)
    before = listing(target)
    again = adopt.adopt_points(target.vault, incoming(source), lambda e: None)
    assert [r.status for r in again] == ["present", "present"] and listing(target) == before


def test_existing_points_are_untouched(tmp_path: Path) -> None:
    source, target = World(tmp_path / "a"), World(tmp_path / "b")
    two_points(source)
    target.write_conversation(jsonl(40, seed=77))
    assert target.capture(reason="sleep").status == "written"
    own = listing(target)
    own_bytes = {p: (target.vault.manifests.unit_dir(CONV) / f"{p}.json").read_bytes() for p in own}
    chunks_before = {sha for sha, _p in target.vault.blobs.all_blobs()}
    adopt.adopt_points(target.vault, incoming(source), lambda e: None)
    after = listing(target)
    assert len(after) == len(own) + 2
    for point, data in own_bytes.items():
        assert (target.vault.manifests.unit_dir(CONV) / f"{point}.json").read_bytes() == data
    assert chunks_before <= {sha for sha, _p in target.vault.blobs.all_blobs()}


def test_a_wrong_byte_is_refused_and_no_point_is_written(tmp_path: Path) -> None:
    source, target = World(tmp_path / "a"), World(tmp_path / "b")
    two_points(source)
    points = incoming(source)
    bad = dataclasses.replace(points[0].files[0], sha256="0" * 64)
    points[0] = dataclasses.replace(points[0], files=(bad, *points[0].files[1:]))
    result = adopt.adopt_points(target.vault, points, lambda e: None)
    assert [r.status for r in result] == ["refused", "adopted"]
    assert points[0].point_id not in listing(target)


def test_an_adopted_point_is_never_thinned(tmp_path: Path) -> None:
    source, target = World(tmp_path / "a"), World(tmp_path / "b")
    two_points(source)
    adopt.adopt_points(target.vault, incoming(source), lambda e: None)
    for point in target.vault.manifests.point_ids(CONV):
        assert target.vault.manifests.is_kept(CONV, point)
    main = target.write_conversation(jsonl(10, seed=3))
    for i in range(20):
        with open(main, "ab") as handle:
            handle.write(jsonl(2, seed=100 + i))
        target.capture(reason="follow")
    retention.thin_unit(target.vault, CONV)
    assert set(listing(source)) <= set(listing(target))


def test_a_relocated_conversation_is_filed_under_its_new_folder(tmp_path: Path) -> None:
    source, target = World(tmp_path / "a"), World(tmp_path / "b")
    two_points(source)
    adopt.adopt_points(target.vault, incoming(source, lambda r: r.replace("-Users-x-proj", "-Users-y-moved")), lambda e: None)
    manifest = target.vault.manifests.newest(CONV)
    assert all("-Users-y-moved" in f.rel for f in manifest.files if f.rel.startswith("projects/"))


def test_undo_removes_only_the_adopted_points(tmp_path: Path) -> None:
    source, target = World(tmp_path / "a"), World(tmp_path / "b")
    two_points(source)
    target.write_conversation(jsonl(40, seed=77))
    target.capture(reason="sleep")
    own = listing(target)
    own_chunks = {c.sha256 for m in target.vault.manifests.points(CONV) for e in m.files for c in e.chunks}
    log: List[dict] = []
    adopt.adopt_points(target.vault, incoming(source), log.append)
    pinned = log[0]
    target.vault.manifests.set_pinned(CONV, pinned["point_id"], True)
    report = adopt.remove_adopted(target.vault, log)
    assert report["removed"] == [f"{CONV}/{log[1]['point_id']}"] and report["kept"] == [f"{CONV}/{pinned['point_id']}"]
    after = listing(target)
    assert set(after) == set(own) | {pinned["point_id"]}
    assert own_chunks <= {sha for sha, _p in target.vault.blobs.all_blobs()}
    report = adopt.remove_adopted(target.vault, [e for e in log if e is not pinned])
    assert report["errors"] == []


def test_undo_of_a_fresh_unit_leaves_no_trace(tmp_path: Path) -> None:
    source, target = World(tmp_path / "a"), World(tmp_path / "b")
    two_points(source)
    log: List[dict] = []
    adopt.adopt_points(target.vault, incoming(source), log.append)
    adopt.remove_adopted(target.vault, log)
    assert target.vault.manifests.units() == []
    assert not any(True for _ in target.vault.blobs.all_blobs())
