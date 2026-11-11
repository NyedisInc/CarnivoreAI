
from __future__ import annotations

import os
import stat
import pytest

from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault import restore
from src.cplugs.sdk.blob_codec import PlaceConflict, place_no_clobber
from src.cplugs.save.vault.manifest import FileEntry, Manifest
from tests.python.cplugs.save.vault_helpers import CONV, World, jsonl


def test_a_restored_file_keeps_its_source_permissions_and_modification_time(tmp_path):
    world = World(tmp_path)
    main = world.write_conversation(jsonl(60), subagents=1, tool_results=0)
    os.chmod(main, 0o600)
    os.utime(main, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    world.capture()
    manifest = world.vault.manifests.newest(CONV)
    out = tmp_path / "restored"
    restore.restore_to_root(world.vault.blobs, manifest, out)
    copy = out / "claude" / manifest.main().rel
    assert stat.S_IMODE(copy.stat().st_mode) == 0o600 and copy.stat().st_mtime_ns == 1_700_000_000_000_000_000
    for entry in manifest.files:
        assert stat.S_IMODE((out / entry.home / entry.rel).stat().st_mode) == entry.mode != 0


def test_an_entry_from_before_modes_were_recorded_is_restored_0644(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(20), subagents=0, tool_results=0)
    world.capture()
    manifest = world.vault.manifests.newest(CONV)
    data = manifest.as_json()
    for entry in data["files"]:
        entry.pop("mode")
        entry.pop("sha_kind")
        entry["sha256"] = __import__("hashlib").sha256(b"".join(restore.read_entry(world.vault.blobs, FileEntry.from_json({**entry, "sha_kind": "chain"})))).hexdigest()
    old = Manifest.from_json(data)
    assert all(f.mode == 0 and f.sha_kind == K.SHA_CONTENT for f in old.files)
    out = tmp_path / "restored"
    restore.restore_to_root(world.vault.blobs, old, out)
    assert stat.S_IMODE((out / "claude" / old.main().rel).stat().st_mode) == K.DEFAULT_RESTORE_MODE == 0o644


def test_a_volume_that_cannot_hard_link_still_restores_and_still_never_overwrites(tmp_path, monkeypatch):
    world = World(tmp_path)
    world.write_conversation(jsonl(20), subagents=0, tool_results=0)
    world.capture()
    manifest = world.vault.manifests.newest(CONV)

    def no_links(src, dst, **kw):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(restore.os, "link", no_links)
    out = tmp_path / "restored"
    result = restore.restore_to_root(world.vault.blobs, manifest, out)
    assert len(result.written) == len(manifest.files)
    copy = out / "claude" / manifest.main().rel
    assert copy.read_bytes() == world.transcript().read_bytes()
    assert not [p for p in out.rglob(".vault-restore-*")]
    with pytest.raises(PlaceConflict):
        place_no_clobber(copy.with_name("x.tmp"), copy)


def _imported_copy_of(world: World, mode: int) -> Manifest:
    data = world.vault.manifests.newest(CONV).as_json()
    data["reason"] = K.REASON_IMPORT
    for entry in data["files"]:
        entry["mode"] = mode
    return Manifest.from_json(data)


def test_a_mode_an_importer_invented_is_not_restored_when_the_original_is_gone(tmp_path):
    world = World(tmp_path)
    main = world.write_conversation(jsonl(20), subagents=1, tool_results=0)
    world.capture()
    imported = _imported_copy_of(world, 0o600)
    import shutil
    shutil.rmtree(main.parent)
    out = tmp_path / "restored"
    restore.restore_to_root(world.vault.blobs, imported, out)
    assert {stat.S_IMODE((out / e.home / e.rel).stat().st_mode) for e in imported.files} == {0o644}


def test_a_mode_an_importer_invented_gives_way_to_the_originals_current_mode(tmp_path):
    world = World(tmp_path)
    main = world.write_conversation(jsonl(20), subagents=0, tool_results=0)
    world.capture()
    imported = _imported_copy_of(world, 0o600)
    os.chmod(main, 0o640)
    out = tmp_path / "restored"
    restore.restore_to_root(world.vault.blobs, imported, out)
    assert stat.S_IMODE((out / "claude" / imported.main().rel).stat().st_mode) == 0o640


def test_a_captured_0600_is_still_restored_0600_when_the_point_is_not_an_import(tmp_path):
    world = World(tmp_path)
    main = world.write_conversation(jsonl(20), subagents=0, tool_results=0)
    os.chmod(main, 0o600)
    world.capture()
    out = tmp_path / "restored"
    restore.restore_to_root(world.vault.blobs, world.vault.manifests.newest(CONV), out)
    assert stat.S_IMODE((out / "claude" / world.vault.manifests.newest(CONV).main().rel).stat().st_mode) == 0o600


def test_new_imports_record_the_source_files_real_mode_and_never_invent_one(tmp_path):
    from src.cplugs.save.vault.old_sources import extras

    path = tmp_path / "a.jsonl"
    path.write_text("{}\n")
    recorded = extras.ExtraFile(path, "table/a.jsonl", 3, "ab" * 32, 1.0, 0o640)
    unknown = extras.ExtraFile(path, "table/b.jsonl", 3, "cd" * 32, 1.0)
    point = extras.point_of(tmp_path, [recorded, unknown], "imp-1")
    assert [f.mode for f in point.files] == [0o640, 0]


def test_the_archive_importer_files_the_copys_mode_not_a_hardcoded_one(tmp_path):
    from types import SimpleNamespace

    from src.cplugs.save.vault.old_sources import apply, model

    def planned(mode_kwargs):
        copy = model.Copy("s", "l", None, 3, "ab" * 32, 1.0, lambda: iter(()), **mode_kwargs)
        return SimpleNamespace(family="claude", unit="u", point_id="p", stamp=1.0, enc="e", tags={}, files=[
            SimpleNamespace(role="transcript", rel="projects/e/u.jsonl", copy=copy)],
            attribution=SimpleNamespace(project_uid=None, project_name="", working_dir=None))

    for kwargs, expected in (({"mode": 0o644}, 0o644), ({}, 0)):
        incoming = apply.to_incoming(planned(kwargs), "run", tmp_path / "c", tmp_path / "x")
        assert incoming.files[0].mode == expected
