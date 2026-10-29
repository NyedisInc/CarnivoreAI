
from __future__ import annotations

import os
from typing import Any, FrozenSet, Iterable, Optional, Tuple

from src.core.mcp_health.cached_files import read_json
from src.core.mcp_health.fold import server_key

SETTINGS_FILES: Tuple[str, ...] = ("settings.local.json", "settings.json")
DISABLED_KEY: str = "disabledMcpjsonServers"


def name_keys(value: Any) -> FrozenSet[str]:
    if not isinstance(value, list):
        return frozenset()
    return frozenset(k for k in (server_key(n) for n in value if isinstance(n, str)) if k)


def project_settings(working_dir: Optional[str]) -> Iterable[dict]:
    if not working_dir:
        return ()
    docs = (read_json(os.path.join(working_dir, ".claude", name)) for name in SETTINGS_FILES)
    return tuple(d for d in docs if isinstance(d, dict))


def disabled_servers(working_dir: Optional[str]) -> FrozenSet[str]:
    keys: FrozenSet[str] = frozenset()
    for doc in project_settings(working_dir):
        keys |= name_keys(doc.get(DISABLED_KEY))
    return keys
