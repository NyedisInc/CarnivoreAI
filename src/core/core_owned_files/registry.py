
from __future__ import annotations

import fnmatch
from types import MappingProxyType
from typing import Mapping, Tuple

CORE_OWNED: Mapping[str, Tuple[str, ...]] = MappingProxyType({
    "huddle": ("huddle.db", "huddle.db-*", "huddle.db.*", "IMPORTED.json"),
})


def is_core_owned(plugin_id: str, relative_path: str) -> bool:
    return any(fnmatch.fnmatchcase(relative_path, pattern) for pattern in CORE_OWNED.get(plugin_id, ()))
