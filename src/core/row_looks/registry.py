
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import structlog

from src.core import resource_push
from src.core.json_artifact import atomic_write_json
from src.core.resource_push.topics import ROW_LOOKS
from src.core.row_looks import palette

FILENAME = "row_looks.json"
MAX_LOOKS = 256
_ID = re.compile(r"^[0-9a-f]{16}$")

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Look:

    color: Optional[str] = None
    icon: Optional[str] = None


_lock = threading.Lock()
_looks: Dict[str, Look] = {}
_file: Optional[Path] = None


def _persist_locked() -> None:
    if _file is not None:
        atomic_write_json(_file, {"version": 1, "looks": {k: {"color": v.color, "icon": v.icon} for k, v in _looks.items()}},
                          log_event="row_looks_write_failed")


def configure(state_directory: Optional[Path]) -> None:
    global _file
    with _lock:
        _file = None if state_directory is None else state_directory / FILENAME
        _looks.clear()
        if _file is None:
            return
        try:
            data = json.loads(_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            logger.error("row_looks_unreadable", path=str(_file), error=str(exc))
            return
        rows = data.get("looks") if isinstance(data, dict) else None
        for row_id, raw in (rows.items() if isinstance(rows, dict) else ()):
            try:
                if not _ID.match(row_id) or not isinstance(raw, dict):
                    raise palette.RowLookRefused("bad entry")
                color, icon = palette.checked(raw.get("color"), raw.get("icon"))
            except palette.RowLookRefused as exc:
                logger.warning("row_look_dropped", row_id=str(row_id)[:32], error=str(exc)[:80])
                continue
            if color or icon:
                _looks[row_id] = Look(color, icon)


def listing() -> Dict[str, Look]:
    with _lock:
        return dict(_looks)


def set_look(row_id: str, fields: Dict[str, Optional[str]]) -> Look:
    with _lock:
        old = _looks.pop(row_id, Look())
        new = Look(fields["color"] if "color" in fields else old.color, fields["icon"] if "icon" in fields else old.icon)
        if new.color or new.icon:
            _looks[row_id] = new
            while len(_looks) > MAX_LOOKS:
                del _looks[next(iter(_looks))]
        else:
            new = Look()
        _persist_locked()
    resource_push.notify(ROW_LOOKS)
    return new


def apply_on_open(row_id: str, color: Optional[str], icon: Optional[str]) -> None:
    fields = {k: v for k, v in (("color", color), ("icon", icon)) if v is not None}
    if fields:
        set_look(row_id, fields)


def forget(row_id: str) -> None:
    with _lock:
        removed = _looks.pop(row_id, None) is not None
        if removed:
            _persist_locked()
    if removed:
        resource_push.notify(ROW_LOOKS)


def reset_for_test() -> None:
    global _file
    with _lock:
        _looks.clear()
        _file = None
