
from __future__ import annotations

import json
from pathlib import Path

from src.core.skill_manager.roots import configured_account_dirs, known_profiles


def _config(path: Path, rows: list) -> Path:
    path.write_text(json.dumps({"provider_accounts": {"accounts": rows}}), encoding="utf-8")
    return path


def test_codex_account_dirs_are_not_claude_profiles(tmp_path):
    managed = tmp_path / "accounts"
    for name in ("joe-imc", "acme", "acme-codex", "orphan"):
        (managed / name).mkdir(parents=True)
    foreign = [str(managed / "acme"), str(managed / "acme-codex")]
    ids = [p.profile_id for p in known_profiles([], home=tmp_path, managed_root=str(managed), foreign_dirs=foreign)]
    assert ids == ["default", "joe-imc", "orphan"]


def test_without_foreign_dirs_every_folder_still_counts(tmp_path):
    managed = tmp_path / "accounts"
    (managed / "orphan").mkdir(parents=True)
    ids = [p.profile_id for p in known_profiles([], home=tmp_path, managed_root=str(managed))]
    assert ids == ["default", "orphan"]


def test_configured_account_dirs_splits_by_provider(tmp_path):
    cfg = _config(tmp_path / "config.json", [
        {"id": "c1", "name": "c1", "provider": "claude", "claude_config_dir": str(tmp_path / "c1")},
        {"id": "x1", "name": "x1", "provider": "codex", "codex_home": str(tmp_path / "x1")},
    ])
    claude, other = configured_account_dirs(cfg)
    assert claude == [("c1", str(tmp_path / "c1"))]
    assert other == [str(tmp_path / "x1")]


def test_unreadable_config_gives_nothing(tmp_path):
    assert configured_account_dirs(tmp_path / "missing.json") == ([], [])
