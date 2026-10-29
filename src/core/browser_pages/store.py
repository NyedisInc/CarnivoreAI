"""The open-page list's file: ``browser_pages.json`` in the state directory, so page rows survive a server restart.

``open_pages.py`` is the one place the list changes and calls :func:`save` at that point; :func:`load` runs once at
startup. This is NOT ``config.json`` (that boundary is ``src/core/config_writer.py``); it is a small separate state
file, written the same careful way: temp file in the same directory, fsync, ``os.replace``.

A bad file never stops boot: a file that is not valid JSON, or not the expected envelope, is moved aside to
``browser_pages.json.corrupt-<unix ts>`` and the list starts empty; a single malformed row is dropped with a warning
and the rest are kept.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger(__name__)

# state directory
FILENAME = "browser_pages.json"
VERSION = 1
_REQUIRED = {"id": str, "key": str, "frame": str, "title": str, "seq": int}


def path_in(directory: Path) -> Path:
    """The list file inside a state directory. Inputs: directory. Output: Path."""
    return directory / FILENAME


def _valid_row(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    if any(not isinstance(row.get(name), kind) or isinstance(row.get(name), bool) for name, kind in _REQUIRED.items()):
        return False
    if not isinstance(row.get("opened_at"), (int, float)) or isinstance(row.get("opened_at"), bool):
        return False
    ref, src = row.get("ref"), row.get("src")
    return (ref is None or isinstance(ref, dict)) and (src is None or isinstance(src, str)) and (ref is not None or src is not None)


def _move_aside(target: Path, reason: str) -> None:
    aside = target.with_name(f"{target.name}.corrupt-{int(time.time())}")
    try:
        os.replace(target, aside)
    except OSError as exc:
        logger.error("browser_pages_corrupt_move_failed", path=str(target), reason=reason, error=str(exc))
        return
    logger.error("browser_pages_file_corrupt", path=str(target), moved_to=str(aside), reason=reason)


def load(target: Path) -> List[Dict[str, Any]]:
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        logger.error("browser_pages_read_failed", path=str(target), error=str(exc))
        return []
    try:
        data = json.loads(text)
    except ValueError as exc:
        _move_aside(target, f"invalid json: {exc}")
        return []
    if not isinstance(data, dict) or not isinstance(data.get("pages"), list):
        _move_aside(target, "unexpected shape")
        return []
    kept = []
    for row in data["pages"]:
        if _valid_row(row):
            kept.append(row)
        else:
            logger.warning("browser_pages_row_dropped", path=str(target), row=repr(row)[:200])
    return kept


def save(target: Path, rows: List[Dict[str, Any]]) -> None:
    temp = target.with_name(f"{target.name}.tmp")
    try:
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump({"version": VERSION, "pages": rows}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    except OSError as exc:
        logger.error("browser_pages_write_failed", path=str(target), error=str(exc))
