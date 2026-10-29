
from __future__ import annotations

import builtins
import json
import os
import time
from pathlib import Path
from typing import List

import pytest

from src.cplugs.save.vault import constants as K, restore
from src.cplugs.save.vault.store import Vault
from src.cplugs.save.vault.verified import Verified
from tests.python.cplugs.save.test_vault_follow import drain, engine_for, rows_of
from tests.python.cplugs.save.vault_helpers import CONV, World, jsonl


@pytest.fixture
def opened(monkeypatch) -> List[str]:
    seen: List[str] = []
    real = builtins.open

    def spy(file, *args, **kwargs):
        if isinstance(file, (str, Path)):
            seen.append(str(file))
        return real(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy)
    return seen


def touched_world(tmp_path: Path):
    world = World(tmp_path)
    main = world.write_conversation(jsonl(60))
    feed = {"rows": rows_of(world)}
    drain(engine_for(world, rows=lambda: feed["rows"]))
    later = time.time() - 3600
    os.utime(main, (later, later))
    feed["rows"] = rows_of(world)
    return world, main, feed


def reads_of(opened: List[str], world: World) -> List[str]:
    return [p for p in opened if p.startswith(str(world.home))]


def test_a_restart_does_not_reread_a_unit_it_already_verified(tmp_path, opened):
    world, _main, feed = touched_world(tmp_path)
    first = engine_for(world, rows=lambda: feed["rows"])
    drain(first)
    assert len(world.vault.manifests.point_ids(CONV)) == 1
    opened.clear()
    restarted = engine_for(world, rows=lambda: feed["rows"])
    results = drain(restarted)
    assert reads_of(opened, world) == [] and sum(r.captured + r.unchanged for r in results) == 0
    assert len(world.vault.manifests.point_ids(CONV)) == 1


def test_a_write_after_the_restart_is_still_captured(tmp_path):
    world, main, feed = touched_world(tmp_path)
    drain(engine_for(world, rows=lambda: feed["rows"]))
    restarted = engine_for(world, rows=lambda: feed["rows"])
    drain(restarted)
    with open(main, "ab") as handle:
        handle.write(jsonl(4, seed=9))
    feed["rows"] = rows_of(world)
    results = drain(restarted)
    assert sum(r.captured for r in results) == 1 and len(world.vault.manifests.point_ids(CONV)) == 1
    again = engine_for(world, rows=lambda: feed["rows"])
    assert sum(r.captured + r.unchanged for r in drain(again)) == 0
    newest = world.vault.manifests.newest(CONV)
    assert b"".join(restore.read_entry(world.vault.blobs, newest.main())) == main.read_bytes()


def test_a_restart_with_a_same_size_rewrite_is_still_caught(tmp_path):
    world, main, feed = touched_world(tmp_path)
    drain(engine_for(world, rows=lambda: feed["rows"]))
    body = bytearray(main.read_bytes())
    body[-5:-2] = b"zzz"
    main.write_bytes(bytes(body))
    feed["rows"] = rows_of(world)
    assert sum(r.captured for r in drain(engine_for(world, rows=lambda: feed["rows"]))) == 1


def test_the_record_drops_a_unit_whose_newest_point_moved_on(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    verified = Verified()
    verified.load(root)
    verified.add("u1", "p1", {"/a": (1, 2)})
    verified.add("u2", "p7", {"/b": (3, 4)})
    assert verified.save(root)
    fresh = Verified()
    assert fresh.load(root) == 2
    fresh.revalidate_unit("u1", "p1")
    fresh.revalidate_unit("u2", "p8")
    assert fresh.signatures == {"/a": (1, 2)}


@pytest.mark.parametrize("content", ["not json", json.dumps({"v": 99, "units": {}}), json.dumps({"v": 1, "units": {"u": "bad"}}), ""])
def test_a_damaged_record_costs_a_verification_not_a_failure(tmp_path, content):
    root = tmp_path / "vault"
    root.mkdir()
    (root / K.VERIFIED_FILE).write_text(content)
    assert Verified().load(root) == 0


def test_a_missing_record_and_an_unwritable_vault_do_not_raise(tmp_path):
    verified = Verified()
    nowhere = tmp_path / "nowhere"
    assert verified.load(nowhere) == 0
    verified.add("u", "p", {"/a": (1, 1)})
    assert verified.save(nowhere) is False
    nowhere.mkdir()
    assert verified.save(nowhere) is True


def test_files_that_are_no_longer_planned_are_forgotten(tmp_path):
    verified = Verified()
    verified.load(tmp_path)
    verified.add("u", "p", {"/a": (1, 1), "/b": (2, 2)})
    verified.prune({"/a"})
    assert verified.signatures == {"/a": (1, 1)}
    assert verified.save(tmp_path) and list(json.loads((tmp_path / K.VERIFIED_FILE).read_text())["units"]["u"][1]) == ["/a"]


@pytest.mark.parametrize("drop_record", [False, True])
def test_a_torn_last_line_is_captured_once_quiet_even_after_a_restart(tmp_path, monkeypatch, drop_record):
    world = World(tmp_path)
    main = world.write_conversation(jsonl(20))
    drain(engine_for(world))
    with open(main, "ab") as handle:
        handle.write(b'{"type":"assistant","text":"last words of a crashed claude')
    drain(engine_for(world))
    if drop_record:
        (world.vault.root / K.VERIFIED_FILE).unlink(missing_ok=True)
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + K.QUIET_TAIL_SECONDS + 60)
    drain(engine_for(world))
    stored = b"".join(restore.read_entry(world.vault.blobs, world.vault.manifests.newest(CONV).main()))
    assert stored == main.read_bytes()


def test_a_proof_is_dropped_when_the_units_newest_point_is_no_longer_the_one_it_was_made_against(tmp_path):
    world, main, feed = touched_world(tmp_path)
    engine = engine_for(world, rows=lambda: feed["rows"])
    drain(engine)
    proven = main.stat()
    original = main.read_bytes()
    main.write_bytes(original + jsonl(3, seed=5))
    assert world.capture().status == "written"
    main.write_bytes(original)
    os.utime(main, ns=(proven.st_atime_ns, proven.st_mtime_ns))
    feed["rows"] = rows_of(world)
    engine._swept_at = None
    assert sum(r.captured for r in drain(engine)) == 1
    assert b"".join(restore.read_entry(world.vault.blobs, world.vault.manifests.newest(CONV).main())) == original


def test_changing_the_vault_root_in_process_does_not_carry_the_old_proofs(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir(), second.mkdir()
    verified = Verified()
    verified.load(first)
    verified.add("u", "p", {"/a": (1, 1)})
    assert verified.save(first)
    verified.load(second)
    assert verified.signatures == {} and verified.save(second) is False
    verified.load(first)
    assert verified.signatures == {"/a": (1, 1)}


def test_the_engine_forgets_proofs_when_the_vault_it_opens_changes(tmp_path):
    world, _main, feed = touched_world(tmp_path)
    engine = engine_for(world, rows=lambda: feed["rows"])
    drain(engine)
    assert engine._verified.signatures
    other = tmp_path / "other-vault"
    other.mkdir()
    (other / "VAULT.json").write_text('{"format": 1}')
    world.vault = Vault(other)
    engine.run_slice()
    assert engine._verified.signatures == {}


def test_a_failed_save_warns_once_until_it_works_again(tmp_path):
    from structlog.testing import capture_logs

    verified = Verified()
    verified.load(tmp_path / "ro")
    verified.add("u", "p", {"/a": (1, 1)})
    with capture_logs() as logs:
        assert not verified.save(tmp_path / "ro") and not verified.save(tmp_path / "ro")
    assert [e["event"] for e in logs].count("vault_verified_write_failed") == 1


@pytest.mark.parametrize("capture_seconds", [1.0, 0.0])
def test_a_tail_that_goes_quiet_during_the_capture_is_not_proven(tmp_path, monkeypatch, capture_seconds):
    world = World(tmp_path)
    main = world.write_conversation(jsonl(20))
    drain(engine_for(world))
    with open(main, "ab") as handle:
        handle.write(b'{"type":"assistant","text":"last words of a crashed claude')
    young = time.time() - (K.QUIET_TAIL_SECONDS - 0.5)
    os.utime(main, (young, young))
    real, skew = time.time, {"seconds": 0.0}
    monkeypatch.setattr(time, "time", lambda: real() + skew["seconds"])
    capture = world.vault.capture

    def slow_capture(*args, **kwargs):
        try:
            return capture(*args, **kwargs)
        finally:
            skew["seconds"] += capture_seconds

    monkeypatch.setattr(world.vault, "capture", slow_capture)
    engine = engine_for(world)
    drain(engine)
    assert not engine._verified.signatures
    skew["seconds"] = K.QUIET_TAIL_SECONDS + 60
    drain(engine_for(world))
    stored = b"".join(restore.read_entry(world.vault.blobs, world.vault.manifests.newest(CONV).main()))
    assert stored == main.read_bytes()


def test_returning_to_an_earlier_vault_sweeps_again_instead_of_trusting_what_the_engine_remembers(tmp_path):
    world, _main, feed = touched_world(tmp_path)
    engine = engine_for(world, rows=lambda: feed["rows"])
    drain(engine)
    sweeps = []
    real = engine._sweep
    engine._sweep = lambda *a, **k: (sweeps.append(a[0].root), real(*a, **k))[1]
    first = world.vault
    other = tmp_path / "other-vault"
    other.mkdir()
    (other / "VAULT.json").write_text('{"format": 1}')
    for vault in (Vault(other), first):
        world.vault = vault
        engine.run_slice()
    assert sweeps == [other, first.root]
