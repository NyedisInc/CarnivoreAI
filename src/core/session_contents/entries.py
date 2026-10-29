
from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import structlog

from src.core.session_contents import constants as C
from src.core.slash_command_discovery_scan import DiscoveredCommand

logger = structlog.get_logger()

Item = Dict[str, Any]


def item(name: str, scope: str, path: Optional[Path | str] = None, description: str = "", detail: str = "") -> Item:
    return {"name": name, "scope": scope, "path": str(path) if path else None, "description": description,
            "detail": detail}


def from_found(found: Iterable[DiscoveredCommand], scope: str, detail: str = "") -> List[Item]:
    return [item(f.command.lstrip("/"), scope, f.source_path, f.description, detail) for f in found]


def read_json(path: Path) -> Dict[str, Any]:
    try:
        if not path.is_file() or path.stat().st_size > C.MAX_READ_BYTES:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("session_contents_json_unreadable", path=str(path), error=type(exc).__name__)
        return {}
    return data if isinstance(data, dict) else {}


def read_toml(path: Path) -> Dict[str, Any]:
    try:
        if not path.is_file() or path.stat().st_size > C.MAX_READ_BYTES:
            return {}
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("session_contents_toml_unreadable", path=str(path), error=type(exc).__name__)
        return {}


def folder_chain(working_dir: Optional[str], stop_at_git: bool = False) -> List[Path]:
    if not working_dir:
        return []
    here = Path(working_dir).expanduser()
    chain = [here, *here.parents][: C.MAX_ANCESTORS + 1]
    if stop_at_git:
        for index, folder in enumerate(chain):
            if (folder / ".git").exists():
                chain = chain[: index + 1]
                break
        else:
            chain = chain[:1]
    return list(reversed(chain))


def real_key(path: Optional[Path | str]) -> Optional[str]:
    if not path:
        return None
    try:
        return str(Path(path).resolve())
    except (OSError, RuntimeError):
        return str(path)


def drop_seen(items: Iterable[Item], seen: set[str]) -> List[Item]:
    out: List[Item] = []
    for entry in items:
        key = real_key(entry["path"])
        if key is not None and key in seen:
            continue
        if key is not None:
            seen.add(key)
        out.append(entry)
    return out


def dedupe(items: Iterable[Item]) -> List[Item]:
    seen: set[Tuple[str, Optional[str]]] = set()
    out: List[Item] = []
    for entry in items:
        key = (entry["name"], entry["path"])
        if key not in seen:
            seen.add(key)
            out.append(entry)
    return out


def section(kind: str, items: Iterable[Item]) -> Dict[str, Any]:
    unique = dedupe(items)
    return {"kind": kind, "items": unique[: C.MAX_ITEMS_PER_SECTION], "truncated": len(unique) > C.MAX_ITEMS_PER_SECTION}


def top_level_keys(doc: Dict[str, Any]) -> str:
    keys = sorted(str(k) for k in doc)
    more = len(keys) - C.MAX_KEYS_SHOWN
    shown = ", ".join(keys[: C.MAX_KEYS_SHOWN])
    return f"{shown} (+{more})" if more > 0 else shown
