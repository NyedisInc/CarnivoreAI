
from __future__ import annotations

import os
import shutil
import time

from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault import retention, summary_disk
from src.cplugs.save.vault.store import Vault
from tests.python.cplugs.save.test_vault_retention_reads import (
    CONV, SMALL, _cold_copy, _counting_reads, _outcome, _pass, _three_units)
from tests.python.cplugs.save.vault_helpers import World


def _boot(world: World) -> Vault:
    return Vault(world.vault.root)


def test_a_restart_parses_no_unchanged_manifest_and_judges_the_same(tmp_path, monkeypatch):
    world = World(tmp_path)
    _three_units(world)
    _pass(world.vault)
    summaries = world.vault.root / K.SUMMARIES_FILE
    assert summaries.is_file(), "a pass left no summary file behind"
    cold = _cold_copy(world, tmp_path, "cold")
    (cold.root / K.SUMMARIES_FILE).unlink()

    booted = _boot(world)
    with _counting_reads(world, monkeypatch) as reads:
        warm = _pass(booted)
    print(f"after restart: {sum(reads.values())} manifests parsed; summary file {summaries.stat().st_size} bytes")
    assert sum(reads.values()) == 0, f"a restart re-parsed unchanged manifests: {dict(reads)}"
    assert booted.manifests.summaries.parses == 0
    assert _outcome(booted, warm) == _outcome(cold, _pass(cold)), "a restarted pass judged differently from a cold one"


def test_a_changed_manifest_is_reparsed_and_vanished_entries_are_dropped(tmp_path, monkeypatch):
    world = World(tmp_path)
    _three_units(world)
    _pass(world.vault)
    store = world.vault.manifests
    touched = store.unit_dir(SMALL) / f"{store.point_ids(SMALL)[0]}.json"
    later = time.time() + 60
    os.utime(touched, (later, later))
    gone_unit = store.unit_dir(CONV)
    shutil.rmtree(gone_unit)

    booted = _boot(world)
    with _counting_reads(world, monkeypatch) as reads:
        retention.assess(booted)
    assert dict(reads) == {str(touched): 1}, f"expected only the touched manifest parsed: {dict(reads)}"
    stored = summary_disk.load((world.vault.root / K.SUMMARIES_FILE).read_bytes())
    assert CONV not in stored and SMALL in stored, f"entries of a vanished unit stayed: {list(stored)}"


def test_a_corrupt_summary_file_is_discarded_and_rebuilt(tmp_path, monkeypatch):
    world = World(tmp_path)
    _three_units(world)
    _pass(world.vault)
    files = sum(len(world.vault.manifests.point_ids(u)) for u in world.vault.manifests.units())
    path = world.vault.root / K.SUMMARIES_FILE
    path.write_bytes(path.read_bytes()[:-20])

    booted = _boot(world)
    with _counting_reads(world, monkeypatch) as reads:
        retention.assess(booted)
    assert sum(reads.values()) == files, "a corrupt summary file was trusted instead of re-reading the manifests"
    assert summary_disk.load(path.read_bytes()), "the rebuilt summary file does not decode"
    with _counting_reads(world, monkeypatch) as again:
        retention.assess(_boot(world))
    assert sum(again.values()) == 0
