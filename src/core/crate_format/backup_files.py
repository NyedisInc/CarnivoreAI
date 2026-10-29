
from __future__ import annotations

from typing import Any, Mapping

from src.core.crate_format.constants import (
    BACKUPS_DATA,
    HOME_PLUGIN_PREFIX,
    LEGACY_BACKUPS_PLUGIN,
    PROVIDES_BACKUP_POINTS,
    ROLE_PLUGIN_FILE,
)

PROVIDES_KEY = "provides"


def is_backup_point_file(role: str, home: str, rel: str, extra: Mapping[str, Any]) -> bool:
    if role != ROLE_PLUGIN_FILE or not home.startswith(HOME_PLUGIN_PREFIX) or not rel.startswith(f"{BACKUPS_DATA}/"):
        return False
    return extra.get(PROVIDES_KEY) == PROVIDES_BACKUP_POINTS or home == f"{HOME_PLUGIN_PREFIX}{LEGACY_BACKUPS_PLUGIN}"
