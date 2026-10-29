
from __future__ import annotations

import os
import stat

from src.cplugs.save.vault import health, restore, units
from tests.python.cplugs.save.test_vault_follow import drain, engine_for
from tests.python.cplugs.save.vault_helpers import CONV, ENC, World, jsonl

SHORT = "_from--Users-x-y"
LONG = "_from-" + "-Users-contributor-" + "a" * 220


def _make(world: World) -> dict:
    world.write_conversation(jsonl(10))
    made = {}
    for name in (SHORT, LONG):
        for rel, body, mode in (("memory/a.md", b"# note\n", 0o640), ("sessions-index.json", b'{"entries": []}', 0o600)):
            path = world.projects / ENC / name / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            os.chmod(path, mode)
            os.utime(path, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
            made[path] = (mode, 1_700_000_000_000_000_000)
    return made


def test_merged_side_folders_are_backed_up_with_the_project_and_restore_identical(tmp_path):
    world = World(tmp_path)
    made = _make(world)
    engine = engine_for(world)
    drain(engine)
    drain(engine)
    assert health.read(world.state)["uncovered"] == 0
    memory = [u for u in world.vault.manifests.units() if u.startswith("memory@")]
    assert len(memory) == 1
    out = tmp_path / "restored"
    restore.restore_to_root(world.vault.blobs, world.vault.manifests.newest(memory[0]), out)
    for path, (mode, mtime) in made.items():
        copy = out / "claude" / "projects" / ENC / path.relative_to(world.projects / ENC)
        assert copy.read_bytes() == path.read_bytes()
        assert stat.S_IMODE(copy.stat().st_mode) == mode and copy.stat().st_mtime_ns == mtime


def test_a_side_folder_is_not_a_conversation_and_a_real_bad_id_still_is_rejected(tmp_path):
    world = World(tmp_path)
    _make(world)
    (world.projects / ENC / "_bad-conversation").mkdir()
    (world.projects / ENC / "_bad-conversation" / "x.txt").write_text("x")
    skipped: list = []
    plans = units.scan_claude(world.sources, skipped=skipped)
    assert skipped == ["_bad-conversation"] and set(plans) == {CONV}
