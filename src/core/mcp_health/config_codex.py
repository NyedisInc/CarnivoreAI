
from __future__ import annotations

import os
import re
import tomllib
from typing import Any, Dict, List, Optional, Tuple

from src.core.mcp_health.cached_files import read_toml
from src.core.mcp_health.servers import ServerSpec, spec_from_entry

CONFIG_FILE: str = "config.toml"
PROJECT_DIR: str = ".codex"
DEFAULT_CODEX_HOME: str = os.path.join(os.path.expanduser("~"), ".codex")
TABLE: str = "mcp_servers"
KEPT_KEYS: frozenset = frozenset({"url", "command", "args", "enabled", "type", "transport"})

_OVERRIDE = re.compile(r"(?:^|\s)(?:-c|--config)(?:=|\s+)" + TABLE + r"\.([A-Za-z0-9_\-]+)\.([A-Za-z0-9_]+)=")
_NEXT_FLAG = re.compile(r"\s+-{1,2}[A-Za-z]")


def _toml_value(text: str) -> Any:
    try:
        return tomllib.loads("v = " + text)["v"]
    except tomllib.TOMLDecodeError:
        return text


def overrides(command: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for match in _OVERRIDE.finditer(command or ""):
        name, key = match.group(1), match.group(2)
        if key not in KEPT_KEYS:
            continue
        rest = command[match.end():]
        stop = _NEXT_FLAG.search(rest)
        text = (rest[: stop.start()] if stop else rest).strip()
        value: Any = None
        while text:
            try:
                value = tomllib.loads("v = " + text)["v"]
                break
            except tomllib.TOMLDecodeError:
                cut = text.rfind(" ")
                if cut <= 0:
                    value = _toml_value(text)
                    break
                text = text[:cut].rstrip()
        out.setdefault(name, {})[key] = value
    return out


def _table(doc: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    table = doc.get(TABLE) if isinstance(doc, dict) else None
    return {n: e for n, e in table.items() if isinstance(e, dict)} if isinstance(table, dict) else {}


def codex_servers(command: str, cwd: Optional[str], codex_home: Optional[str]) -> Tuple[ServerSpec, ...]:
    layers: List[Tuple[str, Dict[str, Dict[str, Any]]]] = [
        ("codex", _table(read_toml(os.path.join(codex_home or DEFAULT_CODEX_HOME, CONFIG_FILE)))),
    ]
    if cwd:
        layers.append(("codex-project", _table(read_toml(os.path.join(cwd, PROJECT_DIR, CONFIG_FILE)))))
    layers.append(("override", overrides(command)))
    merged: Dict[str, Dict[str, Any]] = {}
    scope: Dict[str, str] = {}
    for name_of_layer, table in layers:
        for name, entry in table.items():
            merged.setdefault(name, {}).update({k: v for k, v in entry.items() if k in KEPT_KEYS})
            scope.setdefault(name, name_of_layer)
    specs: List[ServerSpec] = []
    for name, entry in merged.items():
        if entry.get("enabled") is False:
            continue
        spec = spec_from_entry(name, entry, scope[name])
        if spec is not None:
            specs.append(spec)
    return tuple(specs)
