
from __future__ import annotations

import sys
from pathlib import Path

from src.core import theme_paths

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_new_carnivore_name_alone_resolves(monkeypatch, tmp_path):
    monkeypatch.delenv("CLOUDE_USER_THEMES_DIR", raising=False)
    monkeypatch.delenv("CLOUDECODE_USER_THEMES_DIR", raising=False)
    monkeypatch.setenv("CARNIVORE_USER_THEMES_DIR", str(tmp_path))
    assert theme_paths.user_themes_dir() == tmp_path


def test_legacy_cloude_name_alone_still_resolves(monkeypatch, tmp_path):
    monkeypatch.delenv("CARNIVORE_USER_THEMES_DIR", raising=False)
    monkeypatch.delenv("CLOUDECODE_USER_THEMES_DIR", raising=False)
    monkeypatch.setenv("CLOUDE_USER_THEMES_DIR", str(tmp_path))
    assert theme_paths.user_themes_dir() == tmp_path


def test_new_name_wins_over_legacy_when_both_set(monkeypatch, tmp_path):
    current = tmp_path / "current"
    legacy = tmp_path / "legacy"
    monkeypatch.setenv("CARNIVORE_USER_THEMES_DIR", str(current))
    monkeypatch.setenv("CLOUDE_USER_THEMES_DIR", str(legacy))
    assert theme_paths.user_themes_dir() == current


def _clear_env(monkeypatch, tmp_path):
    for name in ("CARNIVORE", "CLOUDE", "CLOUDECODE"):
        monkeypatch.delenv(f"{name}_USER_THEMES_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    support = tmp_path / "Library" / "Application Support"
    support.mkdir(parents=True)
    return support


def test_default_canonical_folder_only(monkeypatch, tmp_path):
    support = _clear_env(monkeypatch, tmp_path)
    (support / "Carnivore Menubar").mkdir()
    assert theme_paths.user_themes_dir() == support / "Carnivore Menubar" / "themes"


def test_default_legacy_folder_only(monkeypatch, tmp_path):
    support = _clear_env(monkeypatch, tmp_path)
    (support / "cloude-code-menubar").mkdir()
    assert theme_paths.user_themes_dir() == support / "cloude-code-menubar" / "themes"


def test_default_neither_folder_gives_canonical_and_creates_nothing(monkeypatch, tmp_path):
    support = _clear_env(monkeypatch, tmp_path)
    assert theme_paths.user_themes_dir() == support / "Carnivore Menubar" / "themes"
    assert list(support.iterdir()) == []


def test_default_both_folders_prefers_canonical(monkeypatch, tmp_path):
    support = _clear_env(monkeypatch, tmp_path)
    (support / "Carnivore Menubar").mkdir()
    (support / "cloude-code-menubar").mkdir()
    assert theme_paths.user_themes_dir() == support / "Carnivore Menubar" / "themes"


def test_override_wins_over_existing_default_folder(monkeypatch, tmp_path):
    support = _clear_env(monkeypatch, tmp_path)
    (support / "Carnivore Menubar").mkdir()
    override = tmp_path / "override"
    monkeypatch.setenv("CARNIVORE_USER_THEMES_DIR", str(override))
    assert theme_paths.user_themes_dir() == override


def test_blank_override_is_ignored(monkeypatch, tmp_path):
    support = _clear_env(monkeypatch, tmp_path)
    (support / "cloude-code-menubar").mkdir()
    monkeypatch.setenv("CARNIVORE_USER_THEMES_DIR", "   ")
    assert theme_paths.user_themes_dir() == support / "cloude-code-menubar" / "themes"
