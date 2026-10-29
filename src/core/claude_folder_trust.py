
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional

import structlog

logger = structlog.get_logger()

TRUST_TRUSTED: str = "trusted"
TRUST_WILL_ASK: str = "will_ask"
TRUST_UNKNOWN: str = "unknown"

CLAUDE_JSON_NAME: str = ".claude.json"


def claude_json_path() -> Path:
    return Path(os.path.expanduser("~")) / CLAUDE_JSON_NAME


def load_trust_map(path: Optional[Path] = None) -> Optional[Dict[str, bool]]:
    target = path or claude_json_path()
    try:
        with open(target, "r", encoding="utf-8") as fh:
            document = json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        logger.info("claude_folder_trust_unreadable", path=str(target), error=type(exc).__name__)
        return None
    projects = document.get("projects") if isinstance(document, dict) else None
    if not isinstance(projects, dict):
        return {}
    return {k: bool((v or {}).get("hasTrustDialogAccepted")) for k, v in projects.items()
            if isinstance(k, str) and isinstance(v, dict)}


def _self_and_parents(folder: str) -> Iterator[str]:
    current = os.path.normpath(folder)
    while True:
        yield current
        parent = os.path.dirname(current)
        if parent == current:
            return
        current = parent


def folder_trust(folder: Optional[str], trust_map: Optional[Mapping[str, Any]]) -> str:
    if not folder or trust_map is None:
        return TRUST_UNKNOWN
    spellings = [folder]
    try:
        real = os.path.realpath(folder)
    except (OSError, ValueError):
        real = None
    if real and real != folder:
        spellings.append(real)
    for spelling in spellings:
        for candidate in _self_and_parents(spelling):
            if trust_map.get(candidate) is True:
                return TRUST_TRUSTED
    return TRUST_WILL_ASK
