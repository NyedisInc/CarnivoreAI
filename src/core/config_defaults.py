
from __future__ import annotations

import copy
from typing import Any

from src.core import auth_defaults

OPTIONAL_KEYS: frozenset[str] = frozenset({"template_path"})


def shipped_defaults() -> dict[str, Any]:
    return {
        "config_version": auth_defaults.CONFIG_VERSION,
        "jwt_expiry_minutes": auth_defaults.JWT_EXPIRY_MINUTES,
        "access_token_ttl_seconds": auth_defaults.ACCESS_TOKEN_TTL_SECONDS,
        "refresh_token_ttl_seconds": auth_defaults.REFRESH_TOKEN_TTL_SECONDS,
        "refresh_grace_seconds": auth_defaults.REFRESH_GRACE_SECONDS,
        "common_slash_commands": [],
        "projects": [],
        "session": {},
        "auth_rate_limits": {},
        "agents": {},
        "uploads": {},
        "providers": {},
    }


def supported_keys() -> frozenset[str]:
    return frozenset(shipped_defaults()) | OPTIONAL_KEYS


def effective_shipped_defaults(
    example: dict | None,
    mine: dict | None = None,
) -> dict[str, Any]:
    combined: dict[str, Any] = copy.deepcopy(example) if example else {}
    if mine:
        model = shipped_defaults()
        for key in mine:
            if key not in combined and key in model:
                combined[key] = copy.deepcopy(model[key])
    return combined
