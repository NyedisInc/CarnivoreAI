
from __future__ import annotations

import re
from pathlib import Path

from src.core import product_identity
from src.core.theme_paths import THEMES_DIR_NAME
from tests.python.design_system._sources import css_of

REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG = REPO_ROOT / "client" / "js" / "i18n" / "catalog.en.js"
GUIDE = REPO_ROOT / "web" / "src" / "lib" / "themes-page" / "BuildYourOwn.svelte"


def _catalog_value(key: str) -> str:
    match = re.search(rf"'{re.escape(key)}':\s*'([^']*)'", CATALOG.read_text(encoding="utf-8"))
    assert match, f"catalog key {key} missing"
    return match.group(1)


def test_guide_path_names_the_folder_the_server_scans() -> None:
    path = _catalog_value("themes.page.guide.path")
    expected = (
        f"~/Library/Application Support/{product_identity.MENUBAR_STATE_DIR_NAME}"
        f"/{THEMES_DIR_NAME}/<id>/"
    )
    assert path == expected
    for legacy in product_identity.LEGACY_MENUBAR_STATE_DIR_NAMES:
        assert legacy not in path


def test_guide_override_names_the_canonical_env_var() -> None:
    override = _catalog_value("themes.page.guide.override")
    canonical, *legacy = product_identity.env_names("USER_THEMES_DIR")
    assert canonical in override
    assert not any(name in override for name in legacy)


def test_guide_sample_block_wraps_instead_of_hiding_a_scroll() -> None:
    css = css_of(GUIDE)
    rule = re.search(r"(?:^|\})\s*\.tbyo-code\s*\{([^}]*)\}", css)
    assert rule, ".tbyo-code rule missing"
    body = rule.group(1)
    assert re.search(r"white-space:\s*pre-wrap", body)
    assert re.search(r"overflow-wrap:\s*anywhere", body)
    assert "max-height" not in body, "a capped height hides the rest behind an overlay scrollbar"
