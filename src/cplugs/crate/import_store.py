
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any, Dict, List

import structlog

from src.cplugs.crate import constants as K
from src.cplugs.sdk import crate_import as ci

logger = structlog.get_logger()


def import_dir(work: Path, import_id: str, *, create: bool = False) -> Path:
    if not ci.IMPORT_ID_RE.match(import_id):
        raise KeyError(import_id)
    folder = Path(work) / K.IMPORTS_DIR / import_id
    if create:
        folder.mkdir(mode=K.FOLDER_MODE, parents=True, exist_ok=True)
    return folder


def append_undo(work: Path, import_id: str, entry: Dict[str, Any]) -> None:
    path = import_dir(work, import_id, create=True) / K.UNDO_FILE
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, K.FILE_MODE)
    try:
        os.write(fd, (json.dumps(entry, sort_keys=True) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def read_undo(work: Path, import_id: str) -> List[Dict[str, Any]]:
    path = import_dir(work, import_id) / K.UNDO_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    out: List[Dict[str, Any]] = []
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            logger.warning("crate_import_undo_line_unreadable", import_id=import_id)
            continue
        if isinstance(entry, dict):
            out.append(entry)
    return out


def write_receipt(work: Path, import_id: str, receipt: Dict[str, Any]) -> None:
    folder = import_dir(work, import_id, create=True)
    target = folder / K.RECEIPT_FILE
    temp = folder / f".{K.RECEIPT_FILE}.{secrets.token_hex(4)}.tmp"
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, K.FILE_MODE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(receipt, handle, sort_keys=True, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    finally:
        if temp.exists():
            os.unlink(temp)


def read_receipt(work: Path, import_id: str) -> Dict[str, Any]:
    path = import_dir(work, import_id) / K.RECEIPT_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise KeyError(import_id) from exc
    except (OSError, ValueError) as exc:
        raise ValueError(f"receipt {import_id} could not be read ({type(exc).__name__})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"receipt {import_id} is not a receipt")
    return data


def list_receipts(work: Path) -> List[Dict[str, Any]]:
    root = Path(work) / K.IMPORTS_DIR
    out: List[Dict[str, Any]] = []
    try:
        names = sorted((p.name for p in root.iterdir() if p.is_dir() and ci.IMPORT_ID_RE.match(p.name)), reverse=True)
    except FileNotFoundError:
        return []
    for name in names:
        try:
            out.append(read_receipt(work, name))
        except KeyError:
            continue
        except ValueError as exc:
            logger.warning("crate_import_receipt_unreadable", import_id=name, error=str(exc))
    return out
