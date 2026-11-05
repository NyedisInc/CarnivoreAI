
from __future__ import annotations

from typing import Any, Optional

from src.core.time_zone import app_time_zone
from src.core.ui_preferences.constants import BUILTIN_LOGIN_LABEL_MAX, OWNER_DISPLAY_NAME_MAX


def check_builtin_login_label(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    label = value.strip()
    if not label or len(label) > BUILTIN_LOGIN_LABEL_MAX:
        raise ValueError(
            f"builtin_login_label must be 1 to {BUILTIN_LOGIN_LABEL_MAX} characters"
        )
    if any(not ch.isprintable() for ch in label):
        raise ValueError("builtin_login_label must not contain control characters")
    return label


def check_owner_display_name(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    name = value.strip()
    if not name or len(name) > OWNER_DISPLAY_NAME_MAX:
        raise ValueError(
            f"owner_display_name must be 1 to {OWNER_DISPLAY_NAME_MAX} characters"
        )
    if any(not ch.isprintable() for ch in name):
        raise ValueError("owner_display_name must not contain control characters")
    return name


def check_account_welcome_seen(value: Any) -> Optional[bool]:
    if value is not None and not isinstance(value, bool):
        raise ValueError("account_welcome_seen must be a boolean")
    return value


def check_time_zone(value: Optional[str]) -> Optional[str]:
    return None if value is None else app_time_zone.validate(value)
