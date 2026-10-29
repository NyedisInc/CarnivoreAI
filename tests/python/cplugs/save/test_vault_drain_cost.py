
from __future__ import annotations

import builtins
import dataclasses
import json
import os
import time
from pathlib import Path
from typing import Iterator, List

import pytest

from src.cplugs.save.vault import constants as K, restore, retention
from src.cplugs.save.vault.chunks import BlobStore
from src.cplugs.save.vault.stamp_memo import StampMemo
from src.cplugs.save.vault.follow import Engine
from src.cplugs.save.vault.manifest import Manifest
from tests.python.cplugs.save.test_vault_follow import drain, engine_for
from tests.python.cplugs.save.vault_helpers import CONV, World, jsonl

SUBAGENTS = 60
TOOL_RESULTS = 40


class FsCalls:

    def __init__(self) -> None:
        self.calls: List[tuple] = []

    def count(self, kind: str, under: Path) -> int:
        prefix = str(under)
        return sum(1 for k, path in self.calls if k == kind and path.startswith(prefix))


@pytest.fixture
def fs(monkeypatch) -> Iterator[FsCalls]:
    seen = FsCalls()

    def spy(module, name: str, kind: str) -> None:
        real = getattr(module, name)

        def wrapper(path, *args, **kwargs):
            if isinstance(path, (str, bytes, os.PathLike)):
                seen.calls.append((kind, os.fsdecode(path)))
            return real(path, *args, **kwargs)

        monkeypatch.setattr(module, name, wrapper)

    spy(os, "stat", "stat")
    spy(os, "lstat", "lstat")
    spy(os, "scandir", "scandir")
    spy(builtins, "open", "open")
    yield seen


HOUR_NS = 3600 * 10 ** 9


def settled(engine: Engine) -> None:
    engine._plans = StampMemo(clock_ns=lambda: time.time_ns() + HOUR_NS)


def main_row(world: World) -> List[dict]:
    st = world.transcript().stat()
    return [{"path": str(world.transcript()), "family": "claude", "kind": "conversation", "conversation_id": CONV,
             "size": st.st_size, "mtime_ns": st.st_mtime_ns, "status": "present", "dataless": 0, "gone_at": None}]


def busy_world(tmp_path: Path):
    world = World(tmp_path)
    world.write_conversation(b'{"type":"user","cwd":"/Users/x/proj"}\n' + jsonl(80), subagents=SUBAGENTS, tool_results=TOOL_RESULTS)
    engine = engine_for(world, rows=lambda: main_row(world))
    settled(engine)
    drain(engine)
    files = len(world.vault.manifests.newest(CONV).files)
    return world, engine, files


def append_line(path: Path, n: int = 1) -> None:
    with open(path, "ab") as handle:
        handle.write(jsonl(n, seed=99))


def stored(world: World, rel_end: str) -> bytes:
    entry = next(f for f in world.vault.manifests.newest(CONV).files if f.rel.endswith(rel_end))
    return b"".join(restore.read_entry(world.vault.blobs, entry))


def test_a_drain_after_a_one_line_append_costs_work_proportional_to_the_change(tmp_path, fs):
    world, engine, files = busy_world(tmp_path)
    assert files > 2 * SUBAGENTS + TOOL_RESULTS
    append_line(world.transcript())
    fs.calls.clear()
    result = engine.run_slice()
    assert result.captured == 1
    assert fs.count("lstat", world.home) == 0
    assert fs.count("stat", world.home) <= files + 30
    assert fs.count("stat", world.state / "vault" / "blobs") <= 30
    assert fs.count("scandir", world.home) <= 2
    assert fs.count("open", world.transcript()) <= 2


def test_a_drain_with_nothing_changed_in_the_files_does_not_walk_or_probe_either(tmp_path, fs):
    world, engine, files = busy_world(tmp_path)
    later = time.time() + 5
    os.utime(world.transcript(), (later, later))
    fs.calls.clear()
    engine.run_slice()
    assert fs.count("lstat", world.home) == 0
    assert fs.count("stat", world.state / "vault" / "blobs") <= 30
    assert fs.count("scandir", world.home) <= 2


def test_an_appended_changed_and_new_sidecar_are_each_captured(tmp_path):
    world, engine, _files = busy_world(tmp_path)
    folder = world.transcript().parent / CONV
    append_line(folder / "subagents" / "agent-3.jsonl", 2)
    meta = folder / "subagents" / "agent-4.meta.json"
    meta.write_text('{"agentType":"y"}')
    later = time.time() + 5
    os.utime(meta, (later, later))
    (folder / "tool-results" / "t-new.txt").write_bytes(b"a result that arrived later")
    append_line(world.transcript())
    assert engine.run_slice().captured == 1
    assert stored(world, "subagents/agent-3.jsonl") == (folder / "subagents" / "agent-3.jsonl").read_bytes()
    assert stored(world, "subagents/agent-4.meta.json") == b'{"agentType":"y"}'
    assert stored(world, "tool-results/t-new.txt") == b"a result that arrived later"
    assert stored(world, f"{CONV}.jsonl") == world.transcript().read_bytes()


def test_a_new_folder_inside_a_listed_tree_is_found_and_a_deleted_file_is_kept(tmp_path):
    world, engine, _files = busy_world(tmp_path)
    folder = world.transcript().parent / CONV
    deep = folder / "workflows" / "run-1"
    deep.mkdir(parents=True)
    (deep / "step.json").write_text('{"step":1}')
    gone = folder / "subagents" / "agent-5.jsonl"
    kept = gone.read_bytes()
    gone.unlink()
    append_line(world.transcript())
    assert engine.run_slice().captured == 1
    assert stored(world, "workflows/run-1/step.json") == b'{"step":1}'
    assert stored(world, "subagents/agent-5.jsonl") == kept


def test_a_folder_whose_modified_time_was_put_back_is_still_seen_to_have_changed(tmp_path):
    world, engine, _files = busy_world(tmp_path)
    folder = world.transcript().parent / CONV / "tool-results"
    before = folder.stat()
    (folder / "t-restored.txt").write_bytes(b"added, then the folder's time was put back")
    os.utime(folder, ns=(before.st_atime_ns, before.st_mtime_ns))
    append_line(world.transcript())
    assert engine.run_slice().captured == 1
    assert stored(world, "tool-results/t-restored.txt") == b"added, then the folder's time was put back"


def test_a_chunk_the_collection_removed_is_not_believed_present(tmp_path):
    world, _engine, _files = busy_world(tmp_path)
    orphan = b"a chunk no point names\n"
    ref, _size, _new = world.vault.blobs.put(orphan)
    assert world.vault.blobs.has(ref.sha256)
    result = retention.collect_garbage(world.vault, grace=0, now=time.time() + 10)
    assert result["removed"] == 1
    assert not world.vault.blobs.has(ref.sha256)
    again, _size, written = world.vault.blobs.put(orphan)
    assert written and again == ref and world.vault.blobs.find(ref.sha256) is not None


def test_a_presence_is_believed_for_a_window_and_an_absence_never(tmp_path):
    now = {"t": 1000.0}
    root = tmp_path / "vault"
    root.mkdir()
    blobs = BlobStore(root, clock=lambda: now["t"])
    ref, _size, _new = blobs.put(b"kept for a while\n")
    blobs.find(ref.sha256)[0].unlink()
    assert blobs.has(ref.sha256)
    now["t"] += K.CHUNK_KNOWN_SECONDS + 1
    assert not blobs.has(ref.sha256)
    other = BlobStore(root)
    other.put(b"kept for a while\n")
    assert blobs.has(ref.sha256)


def test_a_chunk_deleted_by_hand_is_repaired_by_the_next_capture_after_the_window(tmp_path):
    world, engine, _files = busy_world(tmp_path)
    folder = world.transcript().parent / CONV
    victim = next(f for f in world.vault.manifests.newest(CONV).files if f.rel.endswith("subagents/agent-7.meta.json"))
    world.vault.blobs.find(victim.chunks[0].sha256)[0].unlink()
    world.vault.blobs._known_until = 0.0
    append_line(world.transcript())
    assert engine.run_slice().captured == 1
    assert world.vault.blobs.find(victim.chunks[0].sha256) is not None
    assert stored(world, "subagents/agent-7.meta.json") == (folder / "subagents" / "agent-7.meta.json").read_bytes()


def test_a_drain_parses_the_newest_manifest_once_not_once_per_reader(tmp_path, monkeypatch):
    world, engine, _files = busy_world(tmp_path)
    parses: List[int] = []
    real = Manifest.from_json
    monkeypatch.setattr(Manifest, "from_json", staticmethod(lambda data: parses.append(1) or real(data)))
    append_line(world.transcript())
    assert engine.run_slice().captured == 1
    assert len(parses) <= 1


def test_a_manifest_replaced_on_disk_is_read_again_and_a_reader_cannot_change_the_next(tmp_path):
    world, _engine, files = busy_world(tmp_path)
    store = world.vault.manifests
    newest = store.newest(CONV)
    newest.files.pop()
    assert len(store.newest(CONV).files) == files
    with pytest.raises(dataclasses.FrozenInstanceError):
        store.newest(CONV).files[0].rel = "elsewhere"
    path = store.unit_dir(CONV) / f"{newest.point_id}.json"
    data = store.newest(CONV).as_json()
    data["title"] = "renamed behind the store's back"
    path.write_text(json.dumps(data))
    assert store.newest(CONV).title == "renamed behind the store's back"
