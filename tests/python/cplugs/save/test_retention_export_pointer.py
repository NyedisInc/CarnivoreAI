
from __future__ import annotations

import os
import time
from contextlib import closing
from pathlib import Path

import pytest

from src.config import settings
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.exports import store
from src.cplugs.save.vault import retention
from src.cplugs.save.vault.restore import verify_manifest
from tests.python.cplugs.save.vault_helpers import CONV, World, jsonl

OTHER = "99999999-aaaa-bbbb-cccc-1234567890ab"
MAX = 3


def _many_points(world: World, conv: str, count: int) -> None:
    world.write_conversation(jsonl(20), conv=conv)
    world.grow_history(count, conv)


def _point_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, exported: bool) -> Path:
    state = tmp_path / "carnivore-state"
    state.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    if exported:
        assert ensure_db_migrated(state).status == "ok"
        monkeypatch.setattr(store.resource_push, "notify", lambda topic: None)
        bundle = store.Bundle("crate-20261017T000000Z-session-0a0b0c0d", "ab" * 32, "session", time.time(),
                              locations=(store.Location("/Volumes/x/a.crate", time.time()),))
        with closing(connect(db_path_for(state))) as conn:
            store.record_bundle(conn, bundle, [store.Pointer(CONV, "claude", bundle.bundle_id, time.time(), "t")])
    return state


def _record_pointer(state: Path, exported_at: float) -> None:
    bundle = store.Bundle("crate-20261017T000000Z-session-0a0b0c0d", "ab" * 32, "session", exported_at,
                          locations=(store.Location("/Volumes/x/a.crate", exported_at),))
    with closing(connect(db_path_for(state))) as conn:
        store.record_bundle(conn, bundle, [store.Pointer(CONV, "claude", bundle.bundle_id, exported_at, "t")])


def _grow_and_capture(world: World, conv: str, times: int) -> None:
    for i in range(times):
        with open(world.transcript(conv), "ab") as handle:
            handle.write(jsonl(3, seed=100 + i))
        time.sleep(0.02)
        assert world.capture(conv).status == "written"


def test_an_exported_conversation_keeps_its_export_source_and_the_newest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = _point_state(tmp_path, monkeypatch, exported=False)
    assert ensure_db_migrated(state).status == "ok"
    monkeypatch.setattr(store.resource_push, "notify", lambda topic: None)
    world = World(tmp_path)
    manifests = world.vault.manifests
    _many_points(world, CONV, 5)
    points = manifests.points(CONV)
    assert len(points) >= 5 and points[2].created_epoch < points[3].created_epoch
    source = points[2]
    _record_pointer(state, (source.created_epoch + points[3].created_epoch) / 2)
    state_after = retention.assess(world.vault, cap_bytes=1 << 40)
    assert manifests.point_ids(CONV) == [source.point_id, points[-1].point_id], "export source plus the newest"
    assert state_after["protected_units"] == 0
    _grow_and_capture(world, CONV, 4)
    ids = manifests.point_ids(CONV)
    assert len(ids) == 2 and ids[0] == source.point_id and ids[1] != points[-1].point_id, f"source plus the newest: {ids}"
    retention.assess(world.vault, cap_bytes=1 << 40)
    assert manifests.point_ids(CONV) == ids
    for point in manifests.points(CONV):
        verify_manifest(world.vault.blobs, point)


def test_a_failed_pointer_read_drops_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = _point_state(tmp_path, monkeypatch, exported=True)
    world = World(tmp_path)
    _many_points(world, CONV, MAX + 3)
    before = world.vault.manifests.point_ids(CONV)
    db_path_for(state).write_bytes(b"this is not a sqlite database")
    assert retention.thin_unit(world.vault, CONV, max_points=MAX) == []
    assert retention.protection(world.vault, CONV, world.vault.manifests.newest(CONV)) == "export_unknown"
    assert world.vault.manifests.point_ids(CONV) == before


def test_no_database_means_not_exported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _point_state(tmp_path, monkeypatch, exported=False)
    world = World(tmp_path)
    _many_points(world, CONV, MAX + 3)
    assert len(retention.thin_unit(world.vault, CONV, max_points=MAX)) == MAX + 2
    assert retention.protection(world.vault, CONV, world.vault.manifests.newest(CONV)) is None
