
from __future__ import annotations

import json
import os
from pathlib import Path

import src.api.skills_manager_routes as routes
import src.config.provider_accounts as pa
from src.config import settings
from src.core.skill_manager import skill_extensions


def _world(tmp_path: Path, monkeypatch, *, managed: Path, codex_home: str) -> Path:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"provider_accounts": {"accounts": [
        {"id": "c1", "name": "c1", "provider": "claude", "claude_config_dir": str(managed / "c1")},
        {"id": "acme-codex", "name": "nx", "provider": "codex", "codex_home": codex_home},
    ]}}), encoding="utf-8")
    monkeypatch.setattr(settings, "auth_config_file", str(cfg))
    monkeypatch.setattr(routes, "MANAGED_ROOT", str(managed))
    monkeypatch.setattr(pa, "MANAGED_ROOT", str(managed))
    return home


def test_route_drops_configured_codex_home(tmp_path, monkeypatch):
    managed = tmp_path / "accounts"
    for n in ("c1", "acme-codex", "orphan"):
        (managed / n).mkdir(parents=True)
    home = _world(tmp_path, monkeypatch, managed=managed, codex_home=str(managed / "acme-codex"))
    ids = [p.profile_id for p in routes._profiles(home)]
    assert ids == ["default", "c1", "orphan"], ids


def test_symlinked_root_with_realpath_typed_row(tmp_path, monkeypatch):
    real = tmp_path / "real-accounts"
    for n in ("c1", "acme-codex"):
        (real / n).mkdir(parents=True)
    link = tmp_path / "accounts"
    os.symlink(real, link)
    home = _world(tmp_path, monkeypatch, managed=link, codex_home=str(real / "acme-codex"))
    ids = [p.profile_id for p in routes._profiles(home)]
    assert "acme-codex" not in ids, ids


def test_seed_skips_codex_home(tmp_path, monkeypatch):
    managed = tmp_path / "accounts"
    skill = managed / "acme-codex" / "skills" / "codex-addon"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: codex-addon\ndescription: x\nextends: huddle\nguide_rev: 1\n---\nbody\n")
    (managed / "c1").mkdir(parents=True)
    home = _world(tmp_path, monkeypatch, managed=managed, codex_home=str(managed / "acme-codex"))
    skill_extensions.reset_for_tests()
    try:
        stale = skill_extensions.stale_extensions("huddle", 5, home=home)
    finally:
        skill_extensions.reset_for_tests()
    assert [r["name"] for r in stale] == [], stale
