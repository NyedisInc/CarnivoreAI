
from __future__ import annotations

from typing import Any, Optional

from pydantic import ValidationInfo

from src.core.desktop_app import preferences as desktop_preferences


def check_desktop_bools(value: Any, info: ValidationInfo) -> Optional[bool]:
    return None if value is None else desktop_preferences.validate_bool(info.field_name, value)


def check_desktop_hotkey(value: Any) -> Optional[str]:
    return None if value is None else desktop_preferences.validate_hotkey(value)


def check_desktop_terminal_app(value: Any) -> Optional[str]:
    return None if value is None else desktop_preferences.validate_terminal_app(value)


def check_desktop_terminal_custom(value: Any) -> Optional[str]:
    return None if value is None else desktop_preferences.validate_terminal_custom(value)
