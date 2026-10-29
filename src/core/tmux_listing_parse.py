
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog

from src.core.product_identity import is_owned_session_name
from src.core.tmux_control.names import is_control_input_session

logger = structlog.get_logger()

LISTING_FORMAT = "#{session_id}|#{session_created}|#{session_windows}|#{session_name}"

CONTROL_SESSION_NAME = "_carnivore_ctl"


def is_plumbing_session(name: str) -> bool:
    return name == CONTROL_SESSION_NAME or is_control_input_session(name)

FIELD_SEPARATOR = "|"

_MAXSPLIT = 3

_SESSION_ID_RE = re.compile(r"^\$\d+$")

_INTEGER_RE = re.compile(r"^\d+$")

ROW_SEPARATOR = "\n"

LINE_BOUNDARY_CHARS: Tuple[str, ...] = (
    "\n",
    "\r",
    "\v",
    "\f",
    "\x1c",
    "\x1d",
    "\x1e",
    "\x85",
    " ",
    " ",
)


def split_listing_rows(stdout_text: str) -> List[str]:
    rows: List[str] = []
    for raw in (stdout_text or "").split(ROW_SEPARATOR):
        row = raw.rstrip("\r")
        if row.strip():
            rows.append(row)
    return rows


def name_has_line_boundary(name: str) -> bool:
    return any(char in name for char in LINE_BOUNDARY_CHARS)


def parse_listing_row(line: str) -> Optional[Dict[str, Any]]:
    stripped = (line or "").rstrip("\r\n")
    if not stripped.strip():
        return None

    parts = stripped.split(FIELD_SEPARATOR, _MAXSPLIT)
    if len(parts) != _MAXSPLIT + 1:
        return None

    session_id, created_raw, windows_raw, name = parts

    if not _SESSION_ID_RE.match(session_id):
        return None
    if not _INTEGER_RE.match(created_raw):
        return None
    if not _INTEGER_RE.match(windows_raw):
        return None
    if not name:
        return None
    if name_has_line_boundary(name):
        return None

    return {
        "session_id": session_id,
        "created_at_epoch": int(created_raw),
        "window_count": int(windows_raw),
        "name": name,
    }


def resolve_ownership(
    name: str,
    created_at_epoch: int,
    owned_instances: Optional[Set[Tuple[str, int]]],
    owned_names: Optional[Set[str]],
    prefix: str = "",
) -> bool:
    if owned_instances is not None:
        if (name, created_at_epoch) in owned_instances:
            return True
        if any(
            owned_name == name and owned_epoch is not None
            for owned_name, owned_epoch in owned_instances
        ):
            return False

    if owned_names is not None:
        return name in owned_names

    if owned_instances is not None:
        return False

    return bool(prefix) and is_owned_session_name(name)


SCREEN_STAMP_FORMAT = (
    "|#{window_activity}|#{pane_width}|#{pane_height}|#{window_active}|#{pane_active}"
)
SCREEN_STAMP_FIELDS = 5


def _stamp_int(raw: Any) -> Optional[int]:
    text = str(raw).strip()
    return int(text) if text.isdigit() else None


def parse_screen_stamp(fields: Any) -> Dict[str, Any]:
    values = list(fields)
    if len(values) != SCREEN_STAMP_FIELDS:
        return {"window_activity": None, "pane_width": None, "pane_height": None,
                "pane_is_current": None}
    activity, width, height, window_active, pane_active = (_stamp_int(v) for v in values)
    current = None
    if window_active is not None and pane_active is not None:
        current = window_active == 1 and pane_active == 1
    return {"window_activity": activity, "pane_width": width, "pane_height": height,
            "pane_is_current": current}
