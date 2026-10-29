
from __future__ import annotations

import os
import shutil
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault import restore, retention
from src.cplugs.save.vault.store import Vault
from tests.python.cplugs.save.vault_helpers import CONV, World, jsonl

EXPORTED = "99999999-aaaa-bbbb-cccc-1234567890ab"
SMALL = "77777777-aaaa-bbbb-cccc-1234567890ab"


def _points(world: World, conv: str, reasons: list) -> None:
    main = world.transcript(conv)
    mine = []
    for i, reason in enumerate(reasons):
        with open(main, "ab") as handle:
            handle.write(jsonl(4, seed=i + 1000))
        os.utime(main, (time.time() + i, time.time() + i))
        assert world.capture(conv, reason=reason).status == "written"
        if not world.vault.manifests.is_pinned(conv, world.vault.manifests.point_ids(conv)[-1]):
            mine.append(world.vault.manifests.point_ids(conv)[-1])
            world.vault.manifests.set_pinned(conv, mine[-1], True)
    for point_id in mine:
        world.vault.manifests.set_pinned(conv, point_id, False)


def _mark_exported_after(world: World, unit: str, index: int) -> str:
    store = world.vault.manifests
    found = store.points(unit)
    store.mark_exported(unit)
    middle = (found[index].created_epoch + found[index + 1].created_epoch) / 2
    os.utime(store.exported_path(unit), (middle, middle))
    return found[index].point_id


def _expected_history(world: World) -> dict:
    store = world.vault.manifests
    keep, other = set(), set()
    pinned = protected = points = 0
    units = [u for u in store.units() if store.points(u)]
    for unit in units:
        found = store.points(unit)
        points += len(found)
        whole = retention.protection(world.vault, unit, found[-1], retention.ExportTimes()) is not None
        protected += whole
        for index, point in enumerate(found):
            pin = store.is_pinned(unit, point.point_id)
            pinned += pin
            at = store.exported_at(unit)
            source = retention.export_source(found, at) if at is not None else None
            held = whole or pin or store.is_kept(unit, point.point_id) or index == len(found) - 1 or point.point_id == source
            (keep if held else other).update(point.chunk_hashes())
    history = sum(world.vault.blobs.stored_size(h) for h in other - keep)
    return {"units": len(units), "points": points, "pinned": pinned, "protected_units": protected,
            "history_bytes": history, "used_bytes": history + sum(world.vault.blobs.stored_size(h) for h in keep)}


@contextmanager
def _counting_reads(world: World, monkeypatch) -> Iterator[Counter]:
    reads: Counter = Counter()
    real_read_text = Path.read_text
    manifests_dir = str(world.vault.root / K.MANIFESTS_DIR)

    def counting_read_text(self, *args, **kwargs):
        if str(self).startswith(manifests_dir) and self.suffix == ".json":
            reads[str(self)] += 1
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)
    try:
        yield reads
    finally:
        monkeypatch.setattr(Path, "read_text", real_read_text)


def _pass(vault: Vault, cap: int = 1 << 40) -> tuple:
    state = retention.assess(vault, cap_bytes=cap)
    state.pop("checked_at")
    return state, retention.collect_garbage(vault, grace=0)


def _cold_copy(world: World, tmp_path: Path, name: str) -> Vault:
    copy = tmp_path / name
    shutil.copytree(world.vault.root, copy)
    return Vault(copy)


def _outcome(vault: Vault, pass_result: tuple) -> tuple:
    store = vault.manifests
    return (pass_result, {u: store.point_ids(u) for u in store.units()}, sorted(s for s, _p in vault.blobs.all_blobs()))


def _three_units(world: World) -> None:
    for conv in (CONV, EXPORTED, SMALL):
        world.write_conversation(jsonl(40), conv=conv)
    _points(world, CONV, ["kill", "kill"] + ["follow"] * 12)
    _points(world, EXPORTED, ["follow"] * 14)
    _points(world, SMALL, ["follow"] * 3)
    _mark_exported_after(world, EXPORTED, 4)
    world.vault.manifests.set_pinned(CONV, world.vault.manifests.point_ids(CONV)[2], True)


def test_later_passes_parse_only_changed_manifests_and_match_a_cold_pass(tmp_path, monkeypatch):
    world = World(tmp_path)
    _three_units(world)
    store = world.vault.manifests
    with _counting_reads(world, monkeypatch) as first:
        _pass(world.vault)
    files = sum(len(store.point_ids(u)) for u in (CONV, EXPORTED, SMALL))
    cold = _cold_copy(world, tmp_path, "cold2")
    with _counting_reads(world, monkeypatch) as second:
        warm = _pass(world.vault)
    print(f"pass 1 parses: {sum(first.values())}; pass 2 parses: {sum(second.values())} of {files} manifest files "
          f"(one per file per pass before this change); cache {store.summaries.footprint()}")
    assert sum(second.values()) == 0, f"an unchanged manifest was parsed again: {dict(second)}"
    assert _outcome(world.vault, warm) == _outcome(cold, _pass(cold)), "a warm pass judged differently from a cold one"

    touched = store.unit_dir(SMALL) / f"{store.point_ids(SMALL)[0]}.json"
    later = time.time() + 60
    os.utime(touched, (later, later))
    with _counting_reads(world, monkeypatch) as third:
        _pass(world.vault)
    assert dict(third) == {str(touched): 1}, f"expected exactly the touched manifest parsed: {dict(third)}"

    before = store.point_ids(CONV)
    _points(world, CONV, ["follow"])
    cold = _cold_copy(world, tmp_path, "cold4")
    with _counting_reads(world, monkeypatch) as fourth:
        warm = _pass(world.vault)
    newest = store.point_ids(CONV)[-1]
    assert newest not in before and set(fourth) <= {str(store.unit_dir(CONV) / f"{newest}.json")}, dict(fourth)
    assert store.point_ids(CONV) == [before[0], newest]
    assert _outcome(world.vault, warm) == _outcome(cold, _pass(cold)), "a warm pass judged differently from a cold one"
    assert warm[1]["removed"] >= 1
    expected = _expected_history(world)
    assert {k: warm[0][k] for k in expected} == expected


def test_one_pass_reads_each_manifest_once_and_keeps_the_same_points(tmp_path, monkeypatch):
    world = World(tmp_path)
    for conv in (CONV, EXPORTED, SMALL):
        world.write_conversation(jsonl(40), conv=conv)
    _points(world, CONV, ["kill", "kill"] + ["follow"] * 12)
    _points(world, EXPORTED, ["follow"] * 14)
    _points(world, SMALL, ["follow"] * 3)
    world.side_history(3)
    store = world.vault.manifests
    source = _mark_exported_after(world, EXPORTED, 4)
    ids = store.point_ids(CONV)
    store.set_pinned(CONV, ids[2], True)
    exported_ids, small_ids = store.point_ids(EXPORTED), store.point_ids(SMALL)
    stray, _size, _new = world.vault.blobs.put(b"nobody references me\n")
    stray_path, _codec = world.vault.blobs.find(stray.sha256)
    old = time.time() - 10 * 24 * 3600
    os.utime(stray_path, (old, old))

    with _counting_reads(world, monkeypatch) as reads:
        state = retention.assess(world.vault, cap_bytes=1)
        collected = retention.collect_garbage(world.vault, grace=0)

    twice = {path: n for path, n in reads.items() if n > 1}
    print(f"manifest files: {len(ids) + len(exported_ids) + len(small_ids)}, reads: {sum(reads.values())}, "
          f"read more than once: {len(twice)}")
    assert not twice, f"manifests read more than once in one pass: {twice}"

    assert store.point_ids(CONV) == [ids[2], ids[-1]]
    assert store.point_ids(EXPORTED) == [source, exported_ids[-1]] and store.point_ids(SMALL) == small_ids[-1:]
    expected = _expected_history(world)
    assert {k: state[k] for k in expected} == expected and state["over_cap"] is True
    named = {h for unit in (CONV, EXPORTED, SMALL, "side-databases") for point in store.points(unit) for h in point.chunk_hashes()}
    left = {sha for sha, _path in world.vault.blobs.all_blobs()}
    assert left == named and not stray_path.exists() and collected["removed"] >= 1
    for unit in (CONV, EXPORTED, SMALL, "side-databases"):
        for point in store.points(unit):
            restore.verify_manifest(world.vault.blobs, point)
