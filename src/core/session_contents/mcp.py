
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from src.core.session_contents.entries import Item, item


def _transport(entry: Dict[str, Any]) -> str:
    declared = entry.get("type")
    if isinstance(declared, str) and declared:
        return declared
    return "http" if "url" in entry else "stdio"


def server_items(table: Any, scope: str, path: Path, origin: str = "") -> List[Item]:
    if not isinstance(table, dict):
        return []
    out: List[Item] = []
    for name, entry in table.items():
        entry = entry if isinstance(entry, dict) else {}
        transport = _transport(entry)
        command = entry.get("command")
        parts = [transport]
        if transport == "stdio" and isinstance(command, str) and command:
            parts.append(Path(command).name)
        if origin:
            parts.append(f"({origin})")
        out.append(item(str(name), scope, path, detail=" ".join(parts)))
    return out
