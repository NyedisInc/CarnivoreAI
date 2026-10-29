
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.deepsearch import constants as K
from src.core.deepsearch.byte_source import ByteSource, open_source
from src.core.deepsearch.extract import extract
from src.core.deepsearch.live.indexer import rules_for
from src.core.deepsearch.live.reader import RangeReader, read_line

WINDOW_DEFAULT: int = 20
WINDOW_MAX: int = 50
ROLES: Dict[str, str] = {K.KIND_USER: "user", K.KIND_ASSISTANT: "assistant", K.KIND_TOOL: "tool", K.KIND_SUMMARY: "summary"}


class ContextNotFound(LookupError):
    pass


@dataclass(frozen=True)
class LiveFile:

    path: Path
    family: str
    file_kind: str
    end: int
    conversation_id: str = ""
    mark: Optional[str] = None

    @property
    def from_backup(self) -> bool:
        return self.mark == K.VAULT_MARK


def find_file(conn: sqlite3.Connection, conversation_id: str, file_kind: str) -> Optional[LiveFile]:
    row = conn.execute(f"SELECT path, family, file_kind, indexed_offset, conversation_id, base_point_id FROM {K.LIVE_TABLE} "
                       "WHERE conversation_id = ? AND file_kind = ? AND in_scope = 1 ORDER BY indexed_offset DESC LIMIT 1",
                       (conversation_id, file_kind)).fetchone()
    return LiveFile(Path(row[0]), row[1] or "claude", row[2], int(row[3]), row[4], row[5]) if row else None


def _message(spans: List[Tuple[int, int]], source: ByteSource, file: LiveFile, rules: Dict[str, Any], line: int) -> Optional[Dict[str, Any]]:
    offset, length = spans[line]
    raw = read_line(source, offset, length)
    found = extract(raw, rules, file.family) if len(raw) == length and raw.endswith(b"\n") else None
    if found is None:
        return None
    try:
        rec = json.loads(raw)
    except ValueError:
        return None
    stamp, uuid = rec.get("timestamp"), rec.get("uuid")
    return {"line": line, "kind": found[0], "role": ROLES.get(found[0], found[0]), "text": found[1],
            "at": stamp if isinstance(stamp, str) else None, "uuid": uuid if isinstance(uuid, str) else None}


def _walk(spans: List[Tuple[int, int]], source: ByteSource, file: LiveFile, rules: Dict[str, Any], start: int, step: int, want: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    line = start
    while 0 <= line < len(spans) and len(out) < want:
        found = _message(spans, source, file, rules, line)
        if found is not None:
            out.append(found)
        line += step
    return out


def _line_at(spans: List[Tuple[int, int]], source: ByteSource, file: LiveFile, rules: Dict[str, Any], at: str) -> int:
    last = -1
    for line in range(len(spans)):
        found = _message(spans, source, file, rules, line)
        if found is None:
            continue
        last = line
        if found["at"] and found["at"] >= at:
            return line
    if last < 0:
        raise ContextNotFound("the conversation holds no message")
    return last


def _markers(messages: List[Dict[str, Any]], has_before: bool, has_after: bool, marks: List[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for mark in marks:
        stamp = mark.entry_timestamp
        first, last = messages[0]["at"] if messages else None, messages[-1]["at"] if messages else None
        if not messages or not ((not has_before or (first and stamp >= first)) and (not has_after or (last and stamp <= last))):
            continue
        follows = [m["line"] for m in messages if m["uuid"] == mark.entry_uuid or (m["at"] and m["at"] <= stamp)]
        out.append({"id": mark.id, "label": mark.label, "at": stamp, "after_line": max(follows) if follows else None})
    return out


def window(file: LiveFile, overrides: Dict[str, Any], marks: List[Any], *, line: Optional[int] = None, at: Optional[str] = None,
           before_line: Optional[int] = None, after_line: Optional[int] = None, before: int = WINDOW_DEFAULT,
           after: int = WINDOW_DEFAULT) -> Dict[str, Any]:
    before, after = max(1, min(int(before), WINDOW_MAX)), max(1, min(int(after), WINDOW_MAX))
    rules = rules_for(overrides, file.family, file.file_kind)
    source = open_source(str(file.path), file.mark, file.conversation_id, file.file_kind)
    spans = [(offset, len(raw)) for offset, raw in RangeReader(source, 0, file.end)]
    if line is None and at is None and before_line is None and after_line is None:
        raise ContextNotFound("no anchor")
    if before_line is not None:
        older = _walk(spans, source, file, rules, min(before_line, len(spans)) - 1, -1, before + 1)
        newer, anchor = [], None
        has_before, has_after = len(older) > before, True
        older = older[:before]
    elif after_line is not None:
        newer = _walk(spans, source, file, rules, after_line + 1, 1, after + 1)
        older, anchor = [], None
        has_before, has_after = True, len(newer) > after
        newer = newer[:after]
    else:
        anchor = _line_at(spans, source, file, rules, at) if at is not None else line
        if anchor is None or not 0 <= anchor < len(spans):
            raise ContextNotFound("that line is not in the conversation")
        older = _walk(spans, source, file, rules, anchor - 1, -1, before + 1)
        newer = _walk(spans, source, file, rules, anchor, 1, after + 2)
        has_before, has_after = len(older) > before, len(newer) > after + 1
        older, newer = older[:before], newer[:after + 1]
    messages = list(reversed(older)) + newer
    return {"file_kind": file.file_kind, "anchor": anchor, "messages": messages, "has_before": has_before and bool(messages),
            "has_after": has_after and bool(messages), "bookmarks": _markers(messages, has_before, has_after, marks)}
