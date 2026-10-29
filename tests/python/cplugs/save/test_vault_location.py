
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.cplugs.save.vault import location
from src.cplugs.save.vault.location import VaultUnavailable


def test_an_unmounted_volume_raises_and_creates_nothing(tmp_path):
    volumes = tmp_path / "Volumes"
    volumes.mkdir()
    (volumes / "Backup").mkdir()
    root = volumes / "Backup" / "vault"
    with pytest.raises(VaultUnavailable, match="not mounted"):
        location.ensure_root(root, removable_parent=str(volumes), ismount=lambda p: False)
    assert not root.exists()
    assert location.ensure_root(root, removable_parent=str(volumes), ismount=lambda p: True) == root
    assert (root / "VAULT.json").is_file()


def test_a_missing_parent_and_a_foreign_folder_are_refused(tmp_path):
    with pytest.raises(VaultUnavailable, match="no parent"):
        location.ensure_root(tmp_path / "nope" / "vault")
    assert not (tmp_path / "nope").exists()
    stuffed = tmp_path / "docs"
    stuffed.mkdir()
    (stuffed / "report.pdf").write_bytes(b"x")
    with pytest.raises(VaultUnavailable, match="not a vault"):
        location.ensure_root(stuffed)
    assert not (stuffed / "VAULT.json").exists()


def test_the_default_is_under_the_state_folder_and_a_chosen_location_wins(tmp_path):
    from tests.python.cplugs.save.vault_helpers import store_save_settings

    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    state = tmp_path / "state"
    assert location.resolve_root(state, config) == state / "vault"
    store_save_settings(state, {"vaultLocation": str(tmp_path / "big" / "vault")})
    assert location.resolve_root(state, config) == tmp_path / "big" / "vault"
    assert json.loads(config.read_text()) == {}
    store_save_settings(state, {"vaultLocation": ""})
    assert location.resolve_root(state, config) == state / "vault"
