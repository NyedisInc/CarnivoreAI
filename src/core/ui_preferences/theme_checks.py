
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.core import theme_script_consent
from src.core.ui_preferences.constants import MAX_SKILL_FAVORITES, MAX_SKILL_NAME_CHARS, MAX_THEME_FAVORITES, MODEL_ID_RE, THEME_ID_RE


def check_theme_id(value: Optional[str]) -> Optional[str]:
    if value is not None and not THEME_ID_RE.match(value):
        raise ValueError("theme must be a theme id like 'claude' or 'matrix'")
    return value


def check_favorite_theme_ids(value: Optional[List[str]]) -> Optional[List[str]]:
    if value is None:
        return None
    if len(value) > MAX_THEME_FAVORITES:
        raise ValueError(f"at most {MAX_THEME_FAVORITES} favorite themes")
    for theme_id in value:
        if not THEME_ID_RE.match(theme_id):
            raise ValueError("theme_favorites holds theme ids like 'claude' or 'matrix'")
    return list(dict.fromkeys(value))


def check_script_consent(value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    return theme_script_consent.validate_consent_map(value)


def check_model_id(value: Optional[str]) -> Optional[str]:
    if value is None or value == "":
        return value
    if not MODEL_ID_RE.match(value):
        raise ValueError("launch_last_model is not a valid model id")
    return value


def check_favorite_skill_names(value: Optional[List[str]]) -> Optional[List[str]]:
    if value is None:
        return None
    if len(value) > MAX_SKILL_FAVORITES:
        raise ValueError(f"at most {MAX_SKILL_FAVORITES} favorite skills")
    for name in value:
        if not name.strip() or len(name) > MAX_SKILL_NAME_CHARS or any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
            raise ValueError("skill_favorites holds skill names: non-empty, no control characters, at most 200 characters")
    return list(dict.fromkeys(value))
