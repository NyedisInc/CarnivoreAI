
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List

import structlog

from src.core.json_artifact import atomic_write_json

logger = structlog.get_logger(__name__)

FILENAME = "open_files.json"
VERSION = 1
ID_RE = re.compile(r"^[0-9a-f]{16}$")
KINDS = ("file", "diff")
ROOTS = ("user", "workdir", "absolute")
_REQUIRED = {"id": str, "kind": str, "root": str, "path": str, "session_uuid": str, "title": str, "seq": int}


def path_in(directory: Path) -> Path:
    return directory / FILENAME


def valid_row(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    if any(not isinstance(row.get(name), kind) or isinstance(row.get(name), bool) for name, kind in _REQUIRED.items()):
        return False
    if not isinstance(row.get("opened_at"), (int, float)) or isinstance(row.get("opened_at"), bool):
        return False
    if row.get("scope_root") is not None and not isinstance(row["scope_root"], str):
        return False
    return (bool(ID_RE.match(row["id"])) and row["kind"] in KINDS and row["root"] in ROOTS
            and bool(row["path"]) and (row["root"] != "absolute" or
                                    (row["kind"] == "file" and not row["session_uuid"] and
                                     Path(row["path"]).is_absolute())))


def _move_aside(target: Path, reason: str) -> None:
    aside = target.with_name(f"{target.name}.corrupt-{int(time.time())}")
    try:
        os.replace(target, aside)
    except OSError as exc:
        logger.error("open_files_corrupt_move_failed", path=str(target), reason=reason, error=str(exc))
        return
    logger.error("open_files_file_corrupt", path=str(target), moved_to=str(aside), reason=reason)


def load(target: Path) -> List[Dict[str, Any]]:
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        logger.error("open_files_read_failed", path=str(target), error=str(exc))
        return []
    try:
        data = json.loads(text)
    except ValueError as exc:
        _move_aside(target, f"invalid json: {exc}")
        return []
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        _move_aside(target, "unexpected shape")
        return []
    kept = []
    for row in data["files"]:
        if valid_row(row):
            kept.append(row)
        else:
            logger.warning("open_files_row_dropped", path=str(target), row=repr(row)[:200])
    return kept


def save(target: Path, rows: List[Dict[str, Any]]) -> bool:
    return atomic_write_json(target, {"version": VERSION, "files": rows}, log_event="open_files_write_failed")
