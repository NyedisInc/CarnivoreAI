from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.tmux_transport.pane_quote import join_pane_continuations, unquote_pane_path
from src.core.tmux_listing_parse import (
    SCREEN_STAMP_FIELDS,
    SCREEN_STAMP_FORMAT,
    is_plumbing_session,
    parse_screen_stamp,
    split_listing_rows,
)

logger = structlog.get_logger()

DELIMITER = "|"
LEADING_FIELDS = 4
GENERATED_FIELDS = LEADING_FIELDS + SCREEN_STAMP_FIELDS
LENGTH_FIELDS = 2
BOUNDED_SPLITS = GENERATED_FIELDS + LENGTH_FIELDS

PANE_LISTING_FORMAT = (
    "#{pane_dead}|#{pane_pid}|#{session_created}|#{pane_id}"
    + SCREEN_STAMP_FORMAT
    + "|#{n:session_name}|#{n:pane_current_command}"
    "|#{session_name}|#{pane_current_command}|#{q:pane_current_path}"
)


def _int_or_none(raw: str) -> Optional[int]:
    try:
        return int(raw)
    except ValueError:
        return None


def _split_tail(tail: str, name_len: int, command_len: int) -> Optional[tuple[str, str, str]]:
    raw = tail.encode("utf-8")
    delim = DELIMITER.encode()
    name_end = name_len
    command_start = name_end + len(delim)
    command_end = command_start + command_len
    if command_end + len(delim) > len(raw):
        return None
    if raw[name_end:command_start] != delim or raw[command_end:command_end + len(delim)] != delim:
        return None
    try:
        return (raw[:name_end].decode("utf-8"), raw[command_start:command_end].decode("utf-8"),
                raw[command_end + len(delim):].decode("utf-8"))
    except UnicodeDecodeError:
        return None


def parse_pane_listing(stdout_text: str) -> Tuple[List[Dict[str, Any]], int]:
    from src.core.session_status import resolve_pane_status

    seen: set[str] = set()
    rows: List[Dict[str, Any]] = []
    refused = 0
    for line in join_pane_continuations(split_listing_rows(stdout_text)):
        line = line.rstrip("\r")
        if not line.strip():
            continue
        parts = line.split(DELIMITER, BOUNDED_SPLITS)
        if len(parts) != BOUNDED_SPLITS + 1:
            logger.debug("list_pane_status_all_unparseable_row", raw=line)
            refused += 1
            continue
        name_len, command_len = _int_or_none(parts[GENERATED_FIELDS]), _int_or_none(parts[GENERATED_FIELDS + 1])
        tail = _split_tail(parts[-1], name_len, command_len) if None not in (name_len, command_len) else None
        if tail is None:
            logger.warning("list_pane_status_all_length_mismatch", raw=line[:200])
            refused += 1
            continue
        name, command, folder = tail
        if is_plumbing_session(name) or name in seen:
            continue
        seen.add(name)
        pane_dead = parts[0]
        row: Dict[str, Any] = {
            "name": name,
            "pane_dead": pane_dead,
            "pane_current_command": command,
            "pid": _int_or_none(parts[1]),
            "status": resolve_pane_status(pane_dead, command),
            "created_at_epoch": _int_or_none(parts[2]),
            "pane_id": parts[3].strip() or None,
            "pane_current_path": unquote_pane_path(folder) or None,
        }
        row.update(parse_screen_stamp(parts[LEADING_FIELDS:GENERATED_FIELDS]))
        rows.append(row)
    return rows, refused
