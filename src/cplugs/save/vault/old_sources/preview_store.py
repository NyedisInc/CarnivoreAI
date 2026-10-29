
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import structlog

from src.cplugs.save.engine import layout
from src.cplugs.save.vault.old_sources import runs

logger = structlog.get_logger()

FILE_NAME = "previews.json"
MAX_BYTES = 256 * 1024
_MODE = 0o600


def path_of(state: Path) -> Path:
    return runs.runs_dir(state) / FILE_NAME


def load(state: Path) -> Dict[str, Dict[str, Any]]:
    path = path_of(state)
    try:
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("file is larger than the cap")
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("save_import_previews_unreadable", path=str(path), error=str(exc)[:200])
        return {}
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, dict) for k, v in data.items()):
        logger.warning("save_import_previews_unreadable", path=str(path), error="not a fingerprint to counts object")
        return {}
    return data


def save(state: Path, previews: Dict[str, Dict[str, Any]]) -> None:
    path = path_of(state)
    tmp = path.with_name(layout.temp_name())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(previews, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("save_import_previews_not_written", path=str(path), error=str(exc)[:200])
        tmp.unlink(missing_ok=True)
