
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict

import pytest

from src.core.backup_health import constants as HK
from src.core.backup_health import vault_check
from src.plugins.save.offload import constants as C
from src.plugins.save.offload import offload_routes, purge, restore_routes, scrub, upkeep
from src.plugins.save.offload.move import holding_root
from src.plugins.save.vault import health
from src.plugins.sdk.blob_codec import Throttle
from tests.python.cplugs.save.offload.fleet import build_fleet, conv_id, delete_a_chunk, ledger_of, store_settings
from tests.python.cplugs.save.vault_helpers import World

DAY = 86400.0


def offload_all(world: World, count: int) -> float:
    for i in range(1, count + 1):
        offload_routes._run(f"S{i}", False)
    return min(e.offloaded_at for e in ledger_of(world).read().values())


def held_files(world: World, conv: str) -> list:
    return [p for p in (holding_root(world.state) / conv).rglob("*") if p.is_file()] if (holding_root(world.state) / conv).exists() else []


def run_purge(world: World, now: float) -> purge.PurgeResult:
    return purge.run_purge(world.vault, ledger_of(world), holding_root(world.state), now=now)


def digest_tree(world: World) -> Dict[str, str]:
    return {str(p.relative_to(world.home)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(world.home.rglob("*")) if p.is_file()}


def test_a_verified_copy_is_deleted_after_seven_days_and_the_session_still_restores(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 2)
    before = digest_tree(world)
    at = offload_all(world, 2)
    early = run_purge(world, at + 6.9 * DAY)
    assert early.purged == [] and held_files(world, conv_id(1)), "not before the hold period ends"
    result = run_purge(world, at + 7.1 * DAY)
    assert sorted(result.purged) == sorted([conv_id(1), conv_id(2)]) and not held_files(world, conv_id(1)) and not held_files(world, conv_id(2))
    entry = ledger_of(world).get(conv_id(1))
    assert entry.state == C.STATE_OFFLOADED and entry.holding_dir == "" and entry.purged_at == at + 7.1 * DAY
    assert run_purge(world, at + 8 * DAY).purged == [], "a purged conversation is not purged twice"
    back = restore_routes.run_restore("S1", None, False)
    assert {c.status for c in back.conversations} == {"written"}
    assert {k: v for k, v in digest_tree(world).items() if conv_id(1) in k} == {k: v for k, v in before.items() if conv_id(1) in k}


def test_an_unverified_copy_is_kept_and_raises_a_sticky_alert_naming_the_blob(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 2)
    at = offload_all(world, 2)
    bad = delete_a_chunk(world, conv_id(2))
    result = run_purge(world, at + 8 * DAY)
    assert result.purged == [conv_id(1)] and result.kept == {conv_id(2): [bad]}
    assert held_files(world, conv_id(2)) and not held_files(world, conv_id(1))
    assert ledger_of(world).get(conv_id(2)).purged_at is None
    firing = next(v for v in vault_check.check_vault(world.state, 2_000_000_000.0) if v.state == "firing" and v.key.startswith(HK.KEY_VAULT_PURGE_UNVERIFIED))
    assert firing.sticky and firing.severity == "error" and bad in firing.params["blobs"] and "repair-chunks-from-restic.sh" in firing.params["script"]


def test_a_repaired_vault_lets_the_next_purge_finish_and_clears_the_record(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 1)
    at = offload_all(world, 1)
    point = world.vault.manifests.newest(conv_id(1))
    sha = next(iter(point.chunk_hashes()))
    path, _codec = world.vault.blobs.find(sha)
    keep = path.read_bytes()
    path.unlink()
    assert run_purge(world, at + 8 * DAY).kept
    path.write_bytes(keep)
    assert run_purge(world, at + 9 * DAY).purged == [conv_id(1)]
    assert health.read(world.state)["offload_alerts"]["purge"]["conversations"] == []


def test_the_purge_never_deletes_outside_the_holding_folder(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 1)
    at = offload_all(world, 1)
    elsewhere = tmp_path / "precious"
    elsewhere.mkdir()
    (elsewhere / "keep.txt").write_text("mine")
    ledger_of(world).update(conv_id(1), holding_dir=str(elsewhere))
    result = run_purge(world, at + 8 * DAY)
    assert result.purged == [] and (elsewhere / "keep.txt").read_text() == "mine" and conv_id(1) in result.kept


def test_the_scrub_names_a_missing_chunk_and_a_clean_vault_raises_nothing(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 2)
    at = offload_all(world, 2)
    clean = scrub.run_scrub(world.vault, ledger_of(world), now=at)
    assert clean.finished and clean.bad == [] and not health.read(world.state).get("offload_alerts")
    assert not scrub.due(world.vault.root, at + 6 * DAY) and scrub.due(world.vault.root, at + 7.1 * DAY)
    bad = delete_a_chunk(world, conv_id(1))
    found = scrub.run_scrub(world.vault, ledger_of(world), now=at + 7.1 * DAY)
    assert found.bad == [bad]
    firing = next(v for v in vault_check.check_vault(world.state, 2_000_000_000.0) if v.state == "firing" and v.key.startswith(HK.KEY_VAULT_SCRUB_DAMAGED))
    assert firing.sticky and bad in firing.params["blobs"] and "repair-chunks-from-restic.sh" in firing.params["script"]


def test_a_scrub_that_runs_out_of_time_resumes_where_it_stopped(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 3)
    at = offload_all(world, 3)
    bad = delete_a_chunk(world, sorted(ledger_of(world).read())[0])
    pace = Throttle(slice_seconds=0.0, sleep=lambda s: None)
    first = scrub.run_scrub(world.vault, ledger_of(world), now=at, pace=pace)
    assert not first.finished and first.units == 1
    seen = 1
    for _ in range(5):
        step = scrub.run_scrub(world.vault, ledger_of(world), now=at, pace=pace)
        seen += step.units
        if step.finished:
            break
    assert seen == 3 and step.finished and step.bad == [bad]


def test_the_upkeep_purges_only_while_the_switch_is_on_and_always_scrubs(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 1)
    at = offload_all(world, 1)
    store_settings(monkeypatch)
    upkeep.run(world.vault, world.state, at + 8 * DAY, Throttle(sleep=lambda s: None))
    assert held_files(world, conv_id(1)) and scrub_stamp(world) is not None
    store_settings(monkeypatch, offloadEnabled=True)
    upkeep.run(world.vault, world.state, at + 8 * DAY, Throttle(sleep=lambda s: None))
    assert not held_files(world, conv_id(1))


def scrub_stamp(world: World):
    return scrub.last_done(world.vault.root)


def test_the_upkeep_never_raises_into_the_engine(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 1)
    offload_all(world, 1)
    ledger_of(world).path.write_text("{ not json")
    upkeep.run(world.vault, world.state, 2_000_000_000.0, Throttle(sleep=lambda s: None))


def test_the_engine_runs_the_upkeep_on_its_quiet_slices(tmp_path, monkeypatch) -> None:
    from src.plugins.save.vault import follow
    from src.plugins.save.vault.follow import Engine

    world = build_fleet(tmp_path, monkeypatch, 1)
    at = offload_all(world, 1)
    clock = {"t": at + 8 * DAY}
    engine = Engine(lambda: world.vault, world.state, lambda: world.sources, throttle=Throttle(sleep=lambda s: None), clock=lambda: clock["t"])
    for _ in range(4):
        engine.run_slice()
        clock["t"] += follow.ASSESS_SECONDS + 1
    assert not held_files(world, conv_id(1))


def test_a_cut_off_restore_of_a_purged_row_is_settled_without_reading_the_working_directory(tmp_path, monkeypatch) -> None:
    from src.plugins.save.offload import reconcile

    world = build_fleet(tmp_path, monkeypatch, 1)
    at = offload_all(world, 1)
    run_purge(world, at + 8 * DAY)
    cwd = tmp_path / "cwd"
    for file in world.vault.manifests.newest(conv_id(1)).files:
        (cwd / file.home / file.rel).parent.mkdir(parents=True, exist_ok=True)
        (cwd / file.home / file.rel).write_bytes(b"decoy")
    monkeypatch.chdir(cwd)
    ledger_of(world).update(conv_id(1), state=C.STATE_RESTORING)
    outcomes = reconcile.reconcile(world.vault, ledger_of(world), offload_routes.claude_homes(world.sources.claude_roots))
    assert outcomes == {conv_id(1): reconcile.OUTCOME_OFFLOADED}


def test_a_point_that_is_not_the_verified_one_keeps_the_held_files(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 1)
    at = offload_all(world, 1)
    ledger_of(world).update(conv_id(1), manifest_sha256="0" * 64)
    result = run_purge(world, at + 8 * DAY)
    assert result.purged == [] and result.kept == {conv_id(1): []} and held_files(world, conv_id(1))


def test_an_early_purge_after_never_shortens_the_seven_days(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 1)
    at = offload_all(world, 1)
    ledger_of(world).update(conv_id(1), purge_after=at)
    assert run_purge(world, at + 1 * DAY).purged == [] and held_files(world, conv_id(1))
    assert run_purge(world, at + 7.1 * DAY).purged == [conv_id(1)]


def test_the_switch_turned_off_mid_pass_stops_the_next_delete(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 2)
    at = offload_all(world, 2)
    live = store_settings(monkeypatch, offloadEnabled=True)
    real = purge.delete_held

    def delete_then_switch_off(root, folder):
        removed = real(root, folder)
        live["offloadEnabled"] = False
        return removed

    monkeypatch.setattr(purge, "delete_held", delete_then_switch_off)
    upkeep.run(world.vault, world.state, at + 8 * DAY, Throttle(sleep=lambda s: None))
    left = [c for c in (conv_id(1), conv_id(2)) if held_files(world, c)]
    assert len(left) == 1, "exactly one folder was deleted before the switch went off"


def test_a_vault_that_goes_away_mid_check_raises_no_false_alert(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 2)
    at = offload_all(world, 2)
    blobs_dir = world.vault.root / "blobs"
    away = tmp_path / "unmounted-blobs"
    real_get = world.vault.blobs.get

    def unmount_then_read(ref):
        if blobs_dir.exists():
            blobs_dir.rename(away)
        return real_get(ref)

    monkeypatch.setattr(world.vault.blobs, "get", unmount_then_read)
    found = scrub.run_scrub(world.vault, ledger_of(world), now=at)
    assert not found.finished and found.bad == [] and not health.read(world.state).get("offload_alerts")
    away.rename(blobs_dir)
    result = run_purge(world, at + 8 * DAY)
    assert result.cancelled and result.purged == [] and held_files(world, conv_id(1)) and held_files(world, conv_id(2))
    assert not health.read(world.state).get("offload_alerts")


def test_a_purge_pass_is_bounded_by_the_slice(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 3)
    at = offload_all(world, 3)
    pace = Throttle(slice_seconds=0.0, sleep=lambda s: None)
    first = purge.run_purge(world.vault, ledger_of(world), holding_root(world.state), now=at + 8 * DAY, pace=pace)
    assert len(first.purged) == 1 and not first.complete
    total = len(first.purged)
    for _ in range(3):
        total += len(purge.run_purge(world.vault, ledger_of(world), holding_root(world.state), now=at + 8 * DAY, pace=pace).purged)
    assert total == 3


def test_a_row_naming_another_conversations_folder_deletes_nothing(tmp_path, monkeypatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 2)
    at = offload_all(world, 2)
    delete_a_chunk(world, conv_id(2))
    ledger_of(world).update(conv_id(1), holding_dir=str(holding_root(world.state) / conv_id(2)))
    result = run_purge(world, at + 8 * DAY)
    assert conv_id(2) not in result.purged and held_files(world, conv_id(2)) and conv_id(1) in result.kept
