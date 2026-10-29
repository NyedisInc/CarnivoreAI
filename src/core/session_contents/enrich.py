
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import structlog

from src.core import config_files
from src.core.session_contents import constants as C
from src.core.session_contents.entries import Item

logger = structlog.get_logger()

LINE_KINDS = frozenset({C.KIND_INSTRUCTIONS, C.KIND_SKILLS, C.KIND_AGENTS, C.KIND_COMMANDS, C.KIND_OUTPUT_STYLES,
                        C.KIND_SETTINGS, C.KIND_PROMPTS})
LOADED_KINDS = frozenset({C.KIND_INSTRUCTIONS, C.KIND_SETTINGS, C.KIND_HOOKS, C.KIND_MCP})
DISABLED_MARKS = ("not enabled", "disabled")
_CHUNK = 64 * 1024


def count_lines(path: Path) -> Optional[int]:
    try:
        if not path.is_file() or path.stat().st_size > C.MAX_READ_BYTES:
            return None
        total, last = 0, b"\n"
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(_CHUNK), b""):
                total += chunk.count(b"\n")
                last = chunk[-1:]
    except OSError as exc:
        logger.warning("session_contents_lines_unreadable", path=str(path), error=type(exc).__name__)
        return None
    return total + (0 if last == b"\n" else 1)


def open_target(path: Optional[str], working_dir: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not path:
        return None, None
    roots = config_files.resolve_roots(working_dir)
    candidates = [Path(path)]
    try:
        candidates.append(Path(path).resolve())
    except (OSError, RuntimeError):
        pass
    for root_id in ("workdir", "user"):
        root = roots.get(root_id)
        for candidate in candidates if root else ():
            try:
                rel = candidate.relative_to(root).as_posix()
                if config_files.resolve_safe_path(root_id, rel, working_dir).is_file():
                    return root_id, rel
            except (ValueError, config_files.ConfigFileError, OSError):
                continue
    return None, None


def status_of(kind: str, detail: str) -> str:
    if any(mark in detail.lower() for mark in DISABLED_MARKS):
        return C.STATUS_DISABLED
    return C.STATUS_LOADED if kind in LOADED_KINDS else C.STATUS_AVAILABLE


def enrich_item(kind: str, entry: Item, working_dir: Optional[str]) -> Item:
    path = entry["path"]
    entry["lines"] = count_lines(Path(path)) if path and kind in LINE_KINDS else None
    entry["open_root"], entry["open_path"] = open_target(path, working_dir)
    entry["status"] = status_of(kind, entry.get("detail", ""))
    return entry


def enrich(sections: Iterable[Dict[str, Any]], working_dir: Optional[str]) -> List[Dict[str, Any]]:
    done = list(sections)
    for one in done:
        for entry in one["items"]:
            enrich_item(one["kind"], entry, working_dir)
    return done
