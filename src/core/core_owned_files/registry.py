
from __future__ import annotations

import fnmatch
from types import MappingProxyType
from typing import Mapping, Tuple

from src.core.work import folders

_TASK_MANAGER_OWNED: Tuple[str, ...] = ("huddle.db", "huddle.db-*", "huddle.db.*", "IMPORTED.json")
CORE_OWNED: Mapping[str, Tuple[str, ...]] = MappingProxyType({plugin_id: _TASK_MANAGER_OWNED for plugin_id in folders.IDS_NEWEST_FIRST})


def is_core_owned(plugin_id: str, relative_path: str) -> bool:
    return any(fnmatch.fnmatchcase(relative_path, pattern) for pattern in CORE_OWNED.get(plugin_id, ()))
