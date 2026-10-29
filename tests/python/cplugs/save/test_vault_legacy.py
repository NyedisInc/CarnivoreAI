
from __future__ import annotations

import hashlib
import io
import json
import lzma
import tarfile
from pathlib import Path

from src.cplugs.save.vault import legacy, restore
from src.cplugs.sdk.blob_codec import compress
from tests.python.cplugs.save.vault_helpers import CONV, ENC, World, jsonl

SLUG = "My-App"
POINT = "20260915T101010Z-kill"


def _tree_sha(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


def _old_point(world: World, body: bytes, codec: str = "zstd", conv: str = CONV, point: str = POINT, bad_sha: bool = False) -> bytes:
    folder = world.state / "time-machine" / SLUG / conv / point
    folder.mkdir(parents=True)
    pack = (lambda raw: compress(raw, "zstd")) if codec == "zstd" else (lambda raw: lzma.compress(raw))
    (folder / "transcript.jsonl.zst").write_bytes(pack(body))
    agent = jsonl(4, seed=9)
    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode="w") as tar:
        info = tarfile.TarInfo("agent-1.jsonl")
        info.size = len(agent)
        tar.addfile(info, io.BytesIO(agent))
    (folder / "subagents.tar.zst").write_bytes(pack(tar_bytes.getvalue()))
    source = world.projects / ENC / f"{conv}.jsonl"
    (folder / "meta.json").write_text(json.dumps({
        "conversation_id": conv, "reason": "kill", "created_epoch": 1789467010.0, "working_dir": "/Users/x/proj", "project": SLUG,
        "codec": codec, "agent_family": "claude",
        "transcript": {"file": "transcript.jsonl.zst", "raw_bytes": len(body), "source_path": str(source),
                       "sha256": "0" * 64 if bad_sha else hashlib.sha256(body).hexdigest()},
        "subagents": {"file": "subagents.tar.zst", "codec": codec}}), encoding="utf-8")
    return agent


def test_an_old_point_is_migrated_byte_identical_and_the_old_tree_is_untouched(tmp_path):
    world = World(tmp_path)
    body = jsonl(500)
    agent = _old_point(world, body)
    before = _tree_sha(world.state / "time-machine")
    assert [p.key for p in legacy.iter_points(world.state)] == [f"{SLUG}/{CONV}/{POINT}"]
    assert legacy.migrate(world.vault, world.state) == legacy.LegacyProgress(more=False, failed=0)
    assert _tree_sha(world.state / "time-machine") == before
    manifest = world.vault.manifests.newest(CONV)
    assert manifest.legacy_key == f"{SLUG}/{CONV}/{POINT}" and manifest.reason == "kill" and manifest.encoded_folder == ENC
    out = tmp_path / "restored"
    restore.restore_to_root(world.vault.blobs, manifest, out)
    assert (out / "claude" / "projects" / ENC / f"{CONV}.jsonl").read_bytes() == body
    assert (out / "claude" / "projects" / ENC / CONV / "subagents" / "agent-1.jsonl").read_bytes() == agent


def test_migrating_twice_or_after_a_crash_adds_nothing(tmp_path):
    world = World(tmp_path)
    _old_point(world, jsonl(50))
    legacy.migrate(world.vault, world.state)
    legacy.migrate(world.vault, world.state)
    (world.vault.root / "legacy-migrated.json").unlink()
    legacy.migrate(world.vault, world.state)
    assert len(world.vault.manifests.points(CONV)) == 1


def test_an_xz_point_and_a_point_failing_its_recorded_hash(tmp_path):
    world = World(tmp_path)
    other = "5440f51e-018d-47a4-8fdf-c52dbf80f162"
    _old_point(world, jsonl(40, seed=1), codec="lzma")
    _old_point(world, jsonl(40, seed=2), conv=other, bad_sha=True)
    assert legacy.migrate(world.vault, world.state) == legacy.LegacyProgress(more=False, failed=1)
    assert world.vault.manifests.newest(CONV) is not None
    assert world.vault.manifests.newest(other) is None
    assert f"{SLUG}/{other}/{POINT}" not in legacy._read_done(world.vault)
