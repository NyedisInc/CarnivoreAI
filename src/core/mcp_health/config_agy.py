
from __future__ import annotations

import os
from typing import Any, Dict, Tuple

from src.core.mcp_health.cached_files import read_json
from src.core.mcp_health.servers import ServerSpec, spec_from_entry

DEFAULT_CONFIG_DIR: str = os.path.join(os.path.expanduser("~"), ".gemini", "config")
FILE: str = "mcp_config.json"


def _servers(path: str) -> Dict[str, Any]:
    doc = read_json(path)
    servers = doc.get("mcpServers") if isinstance(doc, dict) else None
    return servers if isinstance(servers, dict) else {}


def agy_servers(config_dir: str = DEFAULT_CONFIG_DIR) -> Tuple[ServerSpec, ...]:
    merged: Dict[str, Tuple[Any, str]] = {name: (entry, "user") for name, entry in _servers(os.path.join(config_dir, FILE)).items()}
    settings = read_json(os.path.join(config_dir, "config.json"))
    plugins = settings.get("plugins") if isinstance(settings, dict) else None
    plugins = plugins if isinstance(plugins, dict) else {}
    root = os.path.join(config_dir, "plugins")
    try:
        names = sorted(os.listdir(root))
    except OSError:
        names = []
    for plugin in names:
        state = plugins.get(plugin)
        if isinstance(state, dict) and state.get("enabled") is False:
            continue
        for name, entry in _servers(os.path.join(root, plugin, FILE)).items():
            merged[name] = (entry, "plugin")
    specs = (spec_from_entry(name, entry, scope) for name, (entry, scope) in merged.items())
    return tuple(s for s in specs if s is not None)
