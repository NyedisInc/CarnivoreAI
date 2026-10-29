
from __future__ import annotations

import json
from pathlib import Path

from src.config.provider_accounts import ProviderAccount
from src.core import claude_folder_trust
from src.core.account_switch import session_pin
from src.core.pack.move import account
from src.core.pack.trust_carry import store


def _claude_json(path: Path, trusted: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"projects": {str(k): {"hasTrustDialogAccepted": True} for k in trusted}}))


def test_a_folder_trusted_only_in_the_sessions_profile_is_carried_and_only_for_that_profile(monkeypatch, tmp_path) -> None:
    folder = tmp_path / "hq"
    folder.mkdir()
    larkspur, other = tmp_path / "larkspur", tmp_path / "other"
    default = tmp_path / "home" / ".claude.json"
    _claude_json(default, [])
    _claude_json(larkspur / ".claude.json", [folder])
    _claude_json(other / ".claude.json", [])
    monkeypatch.setattr(claude_folder_trust, "claude_json_path", lambda: default)

    assert store.project_trusted(str(folder), [str(larkspur)])
    assert not store.project_trusted(str(folder), [str(other)])
    assert not store.project_trusted(str(folder), [None])
    assert not store.project_trusted(str(folder), [])
    assert not store.project_trusted(str(folder), [str(larkspur), str(other)])
    assert not store.project_trusted(str(folder), [""])
    _claude_json(default, [folder])
    assert store.project_trusted(str(folder), []) and store.project_trusted(str(folder), [None])


def test_session_profile_dir_resolves_the_pinned_account_to_its_own_config_dir(monkeypatch, tmp_path) -> None:
    ht = ProviderAccount(id="larkspur", name="Larkspur", provider="claude", claude_config_dir=str(tmp_path / "ht"))
    monkeypatch.setattr(session_pin, "all_accounts", lambda config_path: [ht])
    monkeypatch.setattr(session_pin, "pin_for", lambda config_path, uuid: {"u1": "larkspur", "u2": "ghost"}.get(uuid))
    assert account.session_profile_dir(tmp_path / "config.json", "u1") == str(tmp_path / "ht")
    assert account.session_profile_dir(tmp_path / "config.json", "u2") == ""
