
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src.core.backup_health import vault_check, vault_record
from src.plugins.save.offload import ledger as ledger_mod
from src.plugins.save.offload import offload_routes, restore_routes, upkeep
from src.plugins.save.offload.move import holding_root
from src.plugins.sdk import offloaded_marker
from tests.python.cplugs.save.offload.fleet import build_fleet, ledger_of
from tests.python.cplugs.save.offload.test_restore_target_folder import CONV, LONG, SHORT, files_under, long_spelling  # noqa: F401
from tests.python.cplugs.save.vault_helpers import World

NOW = 2_000_000_000.0
LEDGER_ALERT = "backup_health.vault_ledger_unreadable"


def prev_of(world: World) -> Path:
    path = ledger_of(world).path
    return path.with_name(path.name + ".prev")


def lose_the_ledger(world: World, *, keep_prev: bool) -> None:
    ledger_of(world).path.unlink()
    if not keep_prev and prev_of(world).exists():
        prev_of(world).unlink()


def held_files(world: World) -> list:
    return sorted(p.name for p in (holding_root(world.state) / CONV).rglob("*") if p.is_file())


def test_a_missing_ledger_with_files_in_holding_refuses_the_restore(long_spelling: World) -> None:
    assert {c.status for c in offload_routes._run("S1", False).conversations} == {"offloaded"}
    held = held_files(long_spelling)
    lose_the_ledger(long_spelling, keep_prev=False)
    [one] = restore_routes.run_restore("S1", None, False).conversations
    assert one.status == "failed" and "ledger unreadable" in one.detail
    assert files_under(long_spelling, SHORT) == {} and files_under(long_spelling, LONG) == {} and held_files(long_spelling) == held


@pytest.mark.parametrize("evidence", ["holding", "marker", "prev"])
def test_any_one_sign_of_an_offload_makes_a_missing_ledger_unreadable(long_spelling: World, evidence: str, tmp_path: Path) -> None:
    offload_routes._run("S1", False)
    lose_the_ledger(long_spelling, keep_prev=evidence == "prev")
    if evidence != "holding":
        shutil.move(str(holding_root(long_spelling.state)), str(tmp_path / "elsewhere"))
    if evidence != "marker":
        assert offloaded_marker.write(long_spelling.state, [], {})
    with pytest.raises(ledger_mod.LedgerUnreadable):
        ledger_of(long_spelling).read()
    assert ledger_mod.offloaded_units(long_spelling.vault.root, state_dir=long_spelling.state).unreadable


def test_the_keepers_without_a_state_folder_still_see_the_previous_copy(long_spelling: World) -> None:
    offload_routes._run("S1", False)
    lose_the_ledger(long_spelling, keep_prev=True)
    assert ledger_mod.offloaded_units(long_spelling.vault.root).holds("any-unit")
    with pytest.raises(ledger_mod.LedgerUnreadable):
        ledger_mod.protects(long_spelling.vault.root, CONV, "any-point")


def test_a_fresh_install_still_reads_an_absent_ledger_as_empty(tmp_path: Path) -> None:
    (tmp_path / "vault").mkdir()
    (tmp_path / "state").mkdir()
    assert ledger_mod.Ledger(tmp_path / "vault", tmp_path / "state").read() == {}
    assert not ledger_mod.offloaded_units(tmp_path / "vault", state_dir=tmp_path / "state").unreadable


def test_every_write_keeps_the_previous_copy(long_spelling: World) -> None:
    offload_routes._run("S1", False)
    ledger = ledger_of(long_spelling)
    before = json.loads(ledger.path.read_text(encoding="utf-8"))
    ledger.update(CONV, error="something to change")
    assert json.loads(prev_of(long_spelling).read_text(encoding="utf-8")) == before
    assert json.loads(ledger.path.read_text(encoding="utf-8")) != before


def test_the_alert_for_a_lost_ledger_names_its_previous_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = build_fleet(tmp_path, monkeypatch, 1)
    assert {c.status for c in offload_routes._run("S1", False).conversations} == {"offloaded"}
    vault_record.update(world.state, active=True, last_ok_at=NOW, swept_at=NOW, uncovered=0, on_disk=0)
    lose_the_ledger(world, keep_prev=True)
    upkeep.run(world.vault, world.state, NOW)
    [verdict] = [v for v in vault_check.check_vault(world.state, NOW) if v.state == "firing" and v.key.startswith(LEDGER_ALERT)]
    assert str(prev_of(world)) in verdict.params["targets"]
