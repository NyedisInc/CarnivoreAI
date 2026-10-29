
from __future__ import annotations

import json
from pathlib import Path

from src.core.backup_health import vault_record
from src.core.inventory.locations import Locations
from src.core.inventory.vault_claims import vault_root
from src.cplugs.host import data_roots, purge_kept, runtime, state as owner_state
from src.cplugs.host.vault_location_migration import migrate
from tests.python.cplugs.save.vault_helpers import store_save_settings

REAL_SHAPED = {"auth": {"token_ttl": 3600}, "save_pipeline": {"capture_scope": "human", "vault_location": ""},
               "projects_root": "~/carnivore-projects"}


def _config(tmp_path: Path, location: str | None) -> Path:
    data = json.loads(json.dumps(REAL_SHAPED))
    if location is None:
        del data["save_pipeline"]["vault_location"]
    else:
        data["save_pipeline"]["vault_location"] = location
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _save_settings(state: Path) -> dict:
    return json.loads(owner_state.state_path(state).read_text())["cplugs"]["save"]["settings"]


def test_a_set_location_is_copied_once_and_nothing_else_changes(tmp_path: Path) -> None:
    state, chosen = tmp_path / "state", tmp_path / "big" / "vault"
    store_save_settings(state, {})
    config = _config(tmp_path, str(chosen))
    before = config.read_bytes()
    assert migrate(state, config) == str(chosen)
    assert _save_settings(state)["vaultLocation"] == str(chosen)
    assert config.read_bytes() == before and not chosen.exists() and not (state / "vault").exists()
    store_save_settings(state, {"vaultLocation": str(tmp_path / "later")})
    assert migrate(state, config) is None
    assert _save_settings(state)["vaultLocation"] == str(tmp_path / "later")


def test_an_unset_or_blank_location_stays_blank_and_reads_as_the_default(tmp_path: Path) -> None:
    for location in (None, ""):
        state = tmp_path / f"state-{location is None}"
        store_save_settings(state, {})
        config = _config(tmp_path, location)
        assert migrate(state, config) == ""
        assert _save_settings(state) == {"vaultLocation": ""}
        assert vault_record.resolve_root(state, config) == state / "vault"


def test_an_already_migrated_install_is_left_alone(tmp_path: Path) -> None:
    state = tmp_path / "state"
    store_save_settings(state, {"vaultLocation": ""})
    revision = json.loads(owner_state.state_path(state).read_text())["cplugs"]["save"]["revision"]
    assert migrate(state, _config(tmp_path, "/Volumes/Old/vault")) is None
    stored = json.loads(owner_state.state_path(state).read_text())["cplugs"]["save"]
    assert stored["revision"] == revision and stored["settings"] == {"vaultLocation": ""}


def test_with_no_stored_entry_nothing_is_written_and_the_old_value_is_still_read(tmp_path: Path) -> None:
    state = tmp_path / "state"
    config = _config(tmp_path, str(tmp_path / "old" / "vault"))
    assert migrate(state, config) is None and not owner_state.state_path(state).exists()
    assert vault_record.resolve_root(state, config) == tmp_path / "old" / "vault"


def test_core_inventory_and_the_plugin_resolve_the_same_root_through_the_setting(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    config = _config(tmp_path, str(tmp_path / "old" / "vault"))
    store_save_settings(state, {"vaultLocation": str(tmp_path / "new" / "vault")})
    locations = Locations(state_dir=state, config_path=config, homes=(), codex=tmp_path / "codex")
    assert vault_root(locations) == tmp_path / "new" / "vault"
    from src.cplugs.save.vault import location

    assert location.resolve_root(state, config) == tmp_path / "new" / "vault"


def test_the_one_resolver_answers_every_shape_and_the_purge_price_uses_it(tmp_path: Path) -> None:
    save = runtime.find("save").manifest
    vault = next(d for d in save.data if d.id == "vault")
    assert data_roots.decl_root(tmp_path, "save", vault, {}) == tmp_path / "vault"
    assert data_roots.decl_root(tmp_path, "save", vault, {"vaultLocation": "/Volumes/B/v"}) == Path("/Volumes/B/v")
    drafts = next(d for d in runtime.find("reviewboard").manifest.data if d.id == "drafts")
    assert data_roots.decl_root(tmp_path, "reviewboard", drafts, {}) == tmp_path / "cplugs" / "reviewboard" / "drafts"
    rows = {r["id"]: r["location"] for r in purge_kept.kept_stores(tmp_path, save.data, {"vaultLocation": "/Volumes/B/v"})}
    assert rows == {"vault": "/Volumes/B/v", "legacy_points": str(tmp_path / "time-machine")}
