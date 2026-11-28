
from __future__ import annotations

import json
import os
import shutil
import typing
from pathlib import Path

import pytest

from src.core import session_transcript_presence as presence
from src.core.backup_health import vault_check, vault_record
from src.core.claude_config import profile_roots
from src.plugins.save import location_check
from src.plugins.save import routes as save_routes
from src.plugins.save.offload import constants as C
from src.plugins.save.offload import ledger as ledger_mod
from src.plugins.save.offload import offload_routes, restore_routes, upkeep
from src.plugins.save.offload.move import holding_root
from src.plugins.save.port import RestorePoints
from src.plugins.save.vault import adopt, retention
from src.plugins.save.vault import points as vault_points
from src.plugins.sdk import offloaded_marker, restore_points
from src.plugins.sdk.catalog_sentence import catalog_sentence
from tests.python.cplugs.save.offload.fleet import build_fleet, conv_id, ledger_of
from tests.python.cplugs.save.offload.test_offload_point_safety import fallback_point
from tests.python.cplugs.save.vault_helpers import World, jsonl

CONV = conv_id(1)
NOW = 2_000_000_000.0
LEDGER_ALERT = "backup_health.vault_ledger_unreadable"
REPO = Path(__file__).resolve().parents[5]


@pytest.fixture
def offloaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    world = build_fleet(tmp_path, monkeypatch, 1)
    assert {c.status for c in offload_routes._run("S1", False).conversations} == {"offloaded"}
    vault_record.update(world.state, active=True, last_ok_at=NOW, swept_at=NOW, uncovered=0, on_disk=0)
    monkeypatch.setattr(save_routes.RUNTIME, "vault", lambda: world.vault)
    monkeypatch.setattr(save_routes.tf, "projects_dir", lambda: world.projects)
    return world


def lose_the_ledger_but_keep_holding(world: World) -> None:
    ledger = ledger_of(world)
    ledger.path.unlink()
    if ledger.prev.exists():
        ledger.prev.unlink()
    assert offloaded_marker.write(world.state, [], {})
    assert any(p.is_file() for p in holding_root(world.state).rglob("*"))


def newest_id(world: World) -> str:
    return vault_points.list_points(world.vault, CONV)[0]["id"]




def test_the_point_restore_and_bookmark_repair_refuse_a_ledger_lost_with_its_copy(offloaded: World) -> None:
    point = newest_id(offloaded)
    lose_the_ledger_but_keep_holding(offloaded)
    homes = {"claude": offloaded.projects.parent, "claude/projects": offloaded.projects}
    with pytest.raises(vault_points.OffloadedError):
        vault_points.restore_point(offloaded.vault, CONV, point, homes)
    with pytest.raises(restore_points.RestoreFailed):
        RestorePoints(lambda: offloaded.vault).restore_newest(CONV, offloaded.projects)
    assert not offloaded.transcript(CONV).exists()


def test_retention_and_adopt_keep_the_unit_whole_when_the_ledger_is_lost_with_its_copy(offloaded: World) -> None:
    lose_the_ledger_but_keep_holding(offloaded)
    newest = offloaded.vault.manifests.newest(CONV)
    assert retention.protection(offloaded.vault, CONV, newest) == retention.PROTECT_OFFLOAD_UNKNOWN  # type: ignore[arg-type]
    assert retention.may_replace(offloaded.vault, CONV, newest) is False  # type: ignore[arg-type]
    [result] = adopt.adopt_points(offloaded.vault, [fallback_point(jsonl(3, seed=5))], lambda entry: None)
    assert result.status == adopt.REFUSED and result.reason == adopt.REASON_LEDGER_UNREADABLE
    assert retention.thin_unit(offloaded.vault, CONV) == []




def test_the_vault_location_cannot_change_while_conversations_are_offloaded(offloaded: World, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere-vault"
    verdict = location_check.check_settings({"vaultLocation": str(elsewhere)})
    assert verdict.refusal == catalog_sentence(location_check.OFFLOAD_REFUSAL_KEY) and "restore" in verdict.refusal and not elsewhere.exists()
    assert not location_check.check_settings({"vaultLocation": ""}).refusal
    assert {c.status for c in restore_routes.run_restore("S1", None, False).conversations} == {"written"}
    assert not location_check.check_settings({"vaultLocation": str(elsewhere)}).refusal


def test_held_files_alone_refuse_a_move_and_an_unreadable_ledger_does_too(offloaded: World, tmp_path: Path) -> None:
    ledger_of(offloaded).path.write_text("{ not json")
    assert location_check.check_settings({"vaultLocation": str(tmp_path / "e1")}).refusal
    ledger_of(offloaded).path.write_text(json.dumps({"conversations": {}}))
    offloaded_marker.write(offloaded.state, [], {})
    assert location_check.check_settings({"vaultLocation": str(tmp_path / "e2")}).refusal


def test_the_lost_ledger_alert_names_the_previous_copy_only_when_it_exists(offloaded: World) -> None:
    lose_the_ledger_but_keep_holding(offloaded)
    upkeep.run(offloaded.vault, offloaded.state, NOW)
    [verdict] = [v for v in vault_check.check_vault(offloaded.state, NOW) if v.state == "firing" and v.key.startswith(LEDGER_ALERT)]
    assert ".prev" not in verdict.params["targets"] and "vault-offload.json" in verdict.params["targets"]




def test_the_upkeep_pass_raises_the_alert_when_only_held_files_remain(offloaded: World) -> None:
    lose_the_ledger_but_keep_holding(offloaded)
    upkeep.run(offloaded.vault, offloaded.state, NOW)
    assert [v.key for v in vault_check.check_vault(offloaded.state, NOW) if v.state == "firing" and v.key.startswith(LEDGER_ALERT)] == [LEDGER_ALERT]


def test_a_new_error_clears_the_old_code_and_path(offloaded: World) -> None:
    ledger = ledger_of(offloaded)
    ledger.update(CONV, error="first", error_code="present_elsewhere", error_path="/somewhere")
    ledger.update(CONV, error="second")
    entry = ledger.get(CONV)
    assert entry is not None and (entry.error, entry.error_code, entry.error_path) == ("second", "", "")
    ledger.update(CONV, error="third", error_code="failed", error_path="/held")
    entry = ledger.get(CONV)
    assert entry is not None and (entry.error_code, entry.error_path) == ("failed", "/held")


def test_a_held_file_that_differs_writes_its_code_and_path(offloaded: World) -> None:
    side = next(p for p in (holding_root(offloaded.state) / CONV).rglob("*.txt"))
    side.write_bytes(b"x" + side.read_bytes()[1:])
    restore_routes.run_restore("S1", None, False)
    entry = ledger_of(offloaded).get(CONV)
    assert entry is not None and (entry.state, entry.error_code, entry.error_path) == (C.STATE_FAILED, "failed", str(side))


def test_an_unreadable_marker_makes_a_missing_ledger_unreadable(offloaded: World) -> None:
    ledger_of(offloaded).path.unlink()
    ledger_of(offloaded).prev.unlink(missing_ok=True)
    shutil.rmtree(holding_root(offloaded.state))
    (offloaded.state / offloaded_marker.MARKER_FILE).write_text("{ not json")
    assert offloaded_marker.read(offloaded.state, quiet=True).unreadable
    assert "marker" in (ledger_mod.absence_doubt(ledger_of(offloaded).path, offloaded.state) or "")


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any folder")
def test_an_unreadable_folder_in_holding_is_not_an_empty_holding(offloaded: World) -> None:
    ledger_of(offloaded).path.unlink()
    ledger_of(offloaded).prev.unlink(missing_ok=True)
    offloaded_marker.write(offloaded.state, [], {})
    folder = next(p for p in holding_root(offloaded.state).rglob("*") if p.is_dir() and not any(c.is_dir() for c in p.iterdir()))
    for f in list(holding_root(offloaded.state).rglob("*")):
        if f.is_file() and f.parent != folder:
            f.unlink()
    folder.chmod(0)
    try:
        doubt = ledger_mod.absence_doubt(ledger_of(offloaded).path, offloaded.state)
    finally:
        folder.chmod(0o700)
    assert doubt is not None and "cannot be read" in doubt




def test_the_alert_copy_says_the_previous_copy_may_miss_the_last_change() -> None:
    text = (REPO / "client/js/i18n/catalog.en.js").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if "'app_alert.backup_health.vault_ledger_unreadable.detail'" in ln)
    assert "may miss the last change" in line


def test_scan_children_is_annotated_with_the_folder_it_returns() -> None:
    hints = typing.get_type_hints(presence._scan_children)
    assert hints["return"] == typing.Tuple[typing.Optional[Path], typing.Optional[Path]]




def test_a_copy_under_a_managed_profile_is_present_elsewhere(offloaded: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = tmp_path / "accounts" / "work"
    held_copy = profile / "projects" / "-Users-x-other" / f"{CONV}.jsonl"
    held_copy.parent.mkdir(parents=True)
    held_copy.write_bytes(jsonl(5, seed=1))
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"provider_accounts": {"accounts": [{"id": "work", "name": "work", "provider": "claude", "claude_config_dir": str(profile)}]}}))
    monkeypatch.setattr(profile_roots, "_default_config_path", lambda: config)
    profile_roots.reset_profile_roots_cache_for_tests()
    try:
        [one] = restore_routes.run_restore("S1", None, False).conversations
        assert one.status == "present_elsewhere" and one.path == str(held_copy)
        assert not offloaded.transcript(CONV).exists()
        held_copy.unlink()
        assert [c.status for c in restore_routes.run_restore("S1", None, False).conversations] == ["written"]
    finally:
        profile_roots.reset_profile_roots_cache_for_tests()
