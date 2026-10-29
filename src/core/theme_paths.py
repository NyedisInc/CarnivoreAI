
from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.core import product_identity
from src.core.product_identity import env_value

USER_THEMES_DIR_ENV_VAR = "CLOUDE_USER_THEMES_DIR"

THEMES_DIR_NAME = "themes"


def user_themes_dir() -> Path:
    raw = env_value("USER_THEMES_DIR")
    if raw and raw.strip():
        return Path(raw).expanduser()
    user_data = product_identity.resolve_named(
        Path.home() / "Library" / "Application Support",
        product_identity.MENUBAR_STATE_DIR_NAME,
        product_identity.LEGACY_MENUBAR_STATE_DIR_NAMES,
    ).path
    return user_data / THEMES_DIR_NAME


def existing_user_themes_dir() -> Optional[Path]:
    candidate = user_themes_dir()
    return candidate if candidate.is_dir() else None
