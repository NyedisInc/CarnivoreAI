
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

from src.core.agy.transcripts import AGY_HOME, valid_id
from src.core.claude_title_sync import (
    CUSTOM_TITLE_FOUND,
    CUSTOM_TITLE_NO_RECORD,
    CustomTitleRead,
    read_tail_records,
)

_TITLE = re.compile(r'^title:\s*("(?:[^"\\]|\\.)*")\s*$', re.MULTILINE)
_MAX_BYTES = 8192
_HISTORY_TAIL_BYTES = 256 * 1024
_SEEN: Dict[str, Tuple[int, int]] = {}


def _stamp(path: Path) -> Optional[Tuple[int, int]]:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _path(conversation_id: str, home: Optional[Path]) -> Optional[Path]:
    return Path(home or AGY_HOME) / "annotations" / f"{conversation_id}.pbtxt" if valid_id(conversation_id) else None


def changed(conversation_id: Optional[str], home: Optional[Path] = None) -> bool:
    path = _path(conversation_id or "", home)
    stamp = _stamp(path) if path else None
    return stamp is not None and _SEEN.get(str(conversation_id)) != stamp


def read_title(conversation_id: str, home: Optional[Path] = None) -> CustomTitleRead:
    path = _path(conversation_id, home)
    stamp = _stamp(path) if path else None
    if path is None or stamp is None or stamp[1] > _MAX_BYTES:
        return CustomTitleRead(CUSTOM_TITLE_NO_RECORD, detail="agy has no name recorded for this conversation")
    try:
        text = path.read_text(encoding="utf-8")
        match = _TITLE.search(text)
        title = json.loads(match.group(1)).strip() if match else ""
    except (OSError, ValueError):
        return CustomTitleRead(CUSTOM_TITLE_NO_RECORD, detail="agy's annotation file could not be read")
    _SEEN[conversation_id] = stamp
    if not title:
        return CustomTitleRead(CUSTOM_TITLE_NO_RECORD, detail="agy's annotation file carries no title")
    return CustomTitleRead(CUSTOM_TITLE_FOUND, title=title, file_size=stamp[1])


def user_rename_title(
    conversation_id: str,
    *,
    row_created_at: Optional[datetime],
    home: Optional[Path] = None,
) -> Optional[str]:
    if not valid_id(conversation_id) or row_created_at is None:
        return None
    history_path = Path(home or AGY_HOME) / "history.jsonl"
    tail = read_tail_records(str(history_path), tail_bytes=_HISTORY_TAIL_BYTES)
    if not tail.readable:
        return None
    newest_name: Optional[str] = None
    newest_at: Optional[datetime] = None
    for record in tail.records:
        if record.get("type") != "slash_command" or record.get("conversationId") != conversation_id:
            continue
        display = record.get("display")
        ts = record.get("timestamp")
        if not isinstance(display, str) or not isinstance(ts, (int, float)) or isinstance(ts, bool):
            continue
        parts = display.strip().split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "/rename":
            continue
        name = parts[1].strip()
        if not name:
            continue
        try:
            at = datetime.fromtimestamp(float(ts) / 1000.0, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            continue
        if at <= row_created_at:
            continue
        if newest_at is None or at >= newest_at:
            newest_at = at
            newest_name = name
    return newest_name
