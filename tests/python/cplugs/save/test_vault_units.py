
from __future__ import annotations

import os
from src.cplugs.save.vault import health, restore, units
from src.cplugs.save.vault.follow import Engine
from src.cplugs.sdk.blob_codec import Throttle
from tests.python.cplugs.save.vault_helpers import CONV, ENC, World, jsonl


def _engine(world: World) -> Engine:
    return Engine(lambda: world.vault, world.state, lambda: world.sources, throttle=Throttle(sleep=lambda s: None))


def _drain(engine: Engine) -> None:
    for _ in range(100):
        if not engine.run_slice().more:
            return
    raise AssertionError("the engine never finished")


def test_conversations_in_a_container_folder_are_captured_with_their_path_kept(tmp_path):
    world = World(tmp_path)
    other = "99999999-aaaa-bbbb-cccc-1234567890ab"
    world.write_conversation(jsonl(30), conv=other, enc=f"_hold-for-archive/{ENC}")
    world.write_conversation(jsonl(30))
    _drain(_engine(world))
    assert sorted(world.vault.manifests.units()) == sorted([CONV, other])
    held = world.vault.manifests.newest(other)
    assert held.main().rel == f"projects/_hold-for-archive/{ENC}/{other}.jsonl" and held.encoded_folder == f"_hold-for-archive/{ENC}"
    out = tmp_path / "restored"
    restore.restore_to_root(world.vault.blobs, held, out)
    assert (out / "claude" / held.main().rel).read_bytes() == (world.projects / "_hold-for-archive" / ENC / f"{other}.jsonl").read_bytes()


def test_a_transcript_set_aside_beside_its_conversation_and_the_projects_loose_files_are_captured(tmp_path):
    world = World(tmp_path)
    main = world.write_conversation(jsonl(30), subagents=0, tool_results=0)
    aside = main.with_name(f"{CONV}.jsonl.from-old-key-20260902")
    aside.write_bytes(jsonl(5, seed=4))
    (main.parent / "sessions-index.json").write_text('{"entries": []}')
    memory = main.parent / "memory"
    memory.mkdir()
    (memory / "note.md").write_text("remember")
    _drain(_engine(world))
    conv = world.vault.manifests.newest(CONV)
    assert f"projects/{ENC}/{aside.name}" in {f.rel for f in conv.files}
    notes = [u for u in world.vault.manifests.units() if u.startswith("memory@")]
    assert len(notes) == 1
    assert {f.rel for f in world.vault.manifests.newest(notes[0]).files} == {f"projects/{ENC}/memory/note.md", f"projects/{ENC}/sessions-index.json"}


def test_a_name_that_cannot_be_a_unit_id_counts_as_on_disk_and_uncovered(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(30))
    (world.projects / ENC / "my notes.jsonl").write_bytes(jsonl(3))
    _drain(_engine(world))
    record = health.read(world.state)
    assert record["on_disk"] == 2 and record["uncovered"] == 1 and record["uncovered_since"]


def test_a_pass_lists_each_folder_once_whatever_the_number_of_conversations(tmp_path, monkeypatch):
    world = World(tmp_path)
    ids = [f"{n:08d}-aaaa-bbbb-cccc-1234567890ab" for n in range(1, 41)]
    for conv in ids:
        world.write_conversation(jsonl(2), conv=conv, enc=f"-Users-x-p{int(conv[:8]) % 4}", subagents=0, tool_results=0)
    folders = [str(world.projects)] + [str(p) for p in world.projects.iterdir()]
    seen = []
    real = os.scandir

    def counting(path):
        seen.append(str(path))
        return real(path)

    monkeypatch.setattr(units.os, "scandir", counting)
    scanner = units.Scanner(world.sources)
    plans = units.scan_all(world.sources, scanner)
    assert len(plans) == 40
    for conv in ids:
        assert units.plan_for(world.sources, conv, "claude", scanner) is not None
    assert {seen.count(f) for f in folders} == {1}


def test_codex_rollouts_are_walked_once_per_pass_and_archived_ones_are_found(tmp_path):
    world = World(tmp_path)
    world.write_codex(jsonl(5), thread="0199aaaa-bbbb-7ccc-8ddd-eeeeffff0001")
    archived = world.codex / "archived_sessions" / "rollout-2026-03-01T10-00-00-0199aaaa-bbbb-7ccc-8ddd-eeeeffff0002.jsonl"
    archived.parent.mkdir(parents=True)
    archived.write_bytes(jsonl(5))
    (world.codex / "auth.json").write_text("{}")
    scanner = units.Scanner(world.sources)
    plans = units.scan_all(world.sources, scanner)
    assert sorted(plans) == ["0199aaaa-bbbb-7ccc-8ddd-eeeeffff0001", "0199aaaa-bbbb-7ccc-8ddd-eeeeffff0002"]
    assert plans["0199aaaa-bbbb-7ccc-8ddd-eeeeffff0002"].files[0].rel.startswith("archived_sessions/")
    assert units.plan_codex(world.sources, "0199aaaa-bbbb-7ccc-8ddd-eeeeffff0001", scanner) is plans["0199aaaa-bbbb-7ccc-8ddd-eeeeffff0001"]
