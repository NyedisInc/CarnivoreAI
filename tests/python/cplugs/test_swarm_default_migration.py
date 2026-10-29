
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from src.core.db_migration import ensure_db_migrated
from src.cplugs.host import gate, runtime, state as owner_state
from src.cplugs.host.swarm_default_migration import migrate


def _entry(state_dir: Path) -> dict:
    return json.loads(owner_state.state_path(state_dir).read_text())["cplugs"]["huddle"]


def test_manifest_default_is_on() -> None:
    manifest = runtime.find("huddle").manifest
    assert manifest.default_enabled is True
    assert owner_state.default_state(manifest).enabled is True


def test_a_fresh_install_stores_the_swarm_on_with_every_grant(tmp_path: Path) -> None:
    assert migrate(tmp_path, True) is True
    entry = _entry(tmp_path)
    assert entry["enabled"] is True
    assert set(entry["grants"]) == set(runtime.find("huddle").manifest.permissions)
    assert gate.is_on("huddle", tmp_path) is True


def test_an_existing_install_with_nothing_stored_stores_off_and_stays_off(tmp_path: Path) -> None:
    assert migrate(tmp_path, False) is False
    assert _entry(tmp_path) == {**_entry(tmp_path), "enabled": False, "grants": []}
    assert gate.is_on("huddle", tmp_path) is False
    assert migrate(tmp_path, True) is None
    assert owner_state.stored_enabled(tmp_path, "huddle") is False


def test_a_stored_choice_is_untouched_either_way(tmp_path: Path) -> None:
    manifest = runtime.find("huddle").manifest
    owner_state.update(tmp_path, manifest, None, lambda st: replace(st, enabled=True, grants=tuple(manifest.permissions)))
    before = owner_state.state_path(tmp_path).read_bytes()
    assert migrate(tmp_path, False) is None
    assert owner_state.state_path(tmp_path).read_bytes() == before
    owner_state.update(tmp_path, manifest, owner_state.get(tmp_path, manifest).revision, lambda st: replace(st, enabled=False))
    off = owner_state.state_path(tmp_path).read_bytes()
    assert migrate(tmp_path, True) is None
    assert owner_state.state_path(tmp_path).read_bytes() == off


def test_the_datastore_verdict_says_fresh_only_for_a_new_database(tmp_path: Path) -> None:
    first = ensure_db_migrated(tmp_path)
    assert first.status == "ok" and first.fresh_install is True
    assert ensure_db_migrated(tmp_path).fresh_install is False
