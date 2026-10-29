
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


def test_an_entry_from_before_modes_were_recorded_is_restored_owner_only(tmp_path):
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
    assert stat.S_IMODE((out / "claude" / old.main().rel).stat().st_mode) == K.DEFAULT_RESTORE_MODE


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
