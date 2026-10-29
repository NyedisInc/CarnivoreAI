
from __future__ import annotations

import json
from pathlib import Path

from src.core.inventory import state_files
from src.core.inventory.locations import Locations
from src.core.inventory.model import REPORT
from src.core.inventory.vault_claims import STORE_VAULT, vault_manifests, vault_root

CONV = "aaaaaaaa-1111-2222-3333-444444444444"


def _locations(tmp_path: Path, config: dict | None = None) -> Locations:
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    cfg = state / "config.json"
    if config is not None:
        cfg.write_text(json.dumps(config), encoding="utf-8")
    return Locations(state_dir=state, config_path=cfg, homes=(), codex=tmp_path / "codex")


def _manifest(root: Path, conv: str) -> Path:
    point = root / "manifests" / conv / "20261016T000000Z-follow.json"
    point.parent.mkdir(parents=True, exist_ok=True)
    point.write_text("{}", encoding="utf-8")
    return point.parent


def test_a_conversations_vault_manifests_are_reported_never_purged(tmp_path: Path) -> None:
    loc = _locations(tmp_path)
    _manifest(loc.state_dir / "vault", CONV)
    blockers: list = []
    found = vault_manifests(loc, [CONV, "bbbbbbbb-1111-2222-3333-444444444444"], blockers)
    assert [(a.store, a.action, a.count) for a in found] == [(STORE_VAULT, REPORT, 1)] and not blockers


def test_the_vault_folder_and_its_health_record_are_accounted_for_in_the_state_walk(tmp_path: Path) -> None:
    loc = _locations(tmp_path)
    _manifest(loc.state_dir / "vault", CONV)
    (loc.state_dir / "vault-health.json").write_text("{}", encoding="utf-8")
    assert state_files.unaccounted(loc.state_dir) == []


def test_a_vault_at_a_configured_location_is_found_there(tmp_path: Path) -> None:
    elsewhere = tmp_path / "bigdisk" / "vault"
    loc = _locations(tmp_path, {"save_pipeline": {"vault_location": str(elsewhere)}})
    _manifest(elsewhere, CONV)
    assert vault_root(loc) == elsewhere
    assert len(vault_manifests(loc, [CONV], [])) == 1
    assert vault_manifests(_locations(tmp_path / "other"), [CONV], []) == []
