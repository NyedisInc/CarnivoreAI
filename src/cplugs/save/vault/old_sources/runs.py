
from __future__ import annotations

import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List

import structlog

from src.cplugs.save.engine import layout

logger = structlog.get_logger()

RUN_ID_RE = re.compile(r"^imp-\d{8}T\d{6}Z-[0-9a-f]{8}$")
STATE_DONE, STATE_PARTIAL, STATE_NOOP, STATE_UNDONE = "done", "partial", "noop", "undone"
_RECEIPT_SUFFIX = ".receipt.json"
_EXPECTED_SUFFIX = ".expected.json"


class RunError(ValueError):
    pass


def runs_dir(state: Path) -> Path:
    return Path(state) / "cplugs" / "save" / "imports"


def new_run_id() -> str:
    return "imp-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + secrets.token_hex(4)


def check_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not RUN_ID_RE.match(run_id):
        raise RunError(f"not an import run id: {run_id!r}")
    return run_id


def _log_path(state: Path, run_id: str) -> Path:
    return runs_dir(state) / f"{check_run_id(run_id)}.jsonl"


def _write(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    layout.atomic_write_json(path, payload)


def append_undo(state: Path, run_id: str, entry: Dict[str, Any]) -> None:
    path = _log_path(state, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    try:
        os.write(fd, (json.dumps(entry, sort_keys=True) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def read_undo(state: Path, run_id: str) -> List[Dict[str, Any]]:
    try:
        text = _log_path(state, run_id).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    out: List[Dict[str, Any]] = []
    for line in text.splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            logger.warning("save_import_undo_line_unreadable", run_id=run_id)
    return out


def write_expected(state: Path, run_id: str, rows: List[Dict[str, Any]]) -> None:
    _write(runs_dir(state) / f"{check_run_id(run_id)}{_EXPECTED_SUFFIX}", {"points": rows})


def read_expected(state: Path, run_id: str) -> List[Dict[str, Any]]:
    try:
        data = json.loads((runs_dir(state) / f"{check_run_id(run_id)}{_EXPECTED_SUFFIX}").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except ValueError as exc:
        raise RunError(f"expected record of {run_id} unreadable: {exc}") from exc
    return list(data.get("points") or []) if isinstance(data, dict) else []


def write_receipt(state: Path, run_id: str, receipt: Dict[str, Any]) -> None:
    _write(runs_dir(state) / f"{check_run_id(run_id)}{_RECEIPT_SUFFIX}", receipt)


def read_receipt(state: Path, run_id: str) -> Dict[str, Any]:
    path = runs_dir(state) / f"{check_run_id(run_id)}{_RECEIPT_SUFFIX}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise KeyError(run_id) from exc
    except (OSError, ValueError) as exc:
        raise RunError(f"receipt of {run_id} unreadable: {exc}") from exc
    if not isinstance(data, dict):
        raise RunError(f"receipt of {run_id} is not an object")
    return data


def list_receipts(state: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        ids = sorted((p.name[:-len(_RECEIPT_SUFFIX)] for p in runs_dir(state).iterdir() if p.name.endswith(_RECEIPT_SUFFIX)), reverse=True)
    except FileNotFoundError:
        return out
    for run_id in ids:
        try:
            out.append(read_receipt(state, run_id))
        except (KeyError, RunError) as exc:
            logger.warning("save_import_receipt_unreadable", run_id=run_id, error=str(exc)[:200])
    return out
