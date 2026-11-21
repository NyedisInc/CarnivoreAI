
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from src.core.timeline import mapping
from src.core.timeline.context import ExtractContext, LineScope
from src.core.timeline.extract_message import ident
from src.core.timeline.model import Kind, Pos, TimelineEvent
from src.core.timeline.prompts import ORIGIN_OTHER

STUB_HEAD_BYTES: int = 4096
MAX_CALL_ID_CHARS: int = 120

_TOOL_USE_ID_RE = re.compile(r'"tool_use_id"\s*:\s*"([^"]{1,%d})"' % MAX_CALL_ID_CHARS)
_TOOL_RESULT_VALUE = '"tool_result"'


class OversizeSerialError(ValueError):
    pass


def _read_string(head: str, start: int) -> Tuple[Optional[str], int]:
    index, chars = start + 1, []
    while index < len(head):
        char = head[index]
        if char == "\\":
            chars.append(head[index + 1:index + 2])
            index += 2
            continue
        if char == '"':
            return "".join(chars), index + 1
        chars.append(char)
        index += 1
    return None, index


def scan_head(head: str) -> Dict[str, str]:
    found: Dict[str, str] = {}
    depth, keys, index = 0, {}, 0
    while index < len(head):
        char = head[index]
        if char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
        elif char == '"':
            text, index = _read_string(head, index)
            if text is None:
                break
            rest = head[index:].lstrip()
            if rest.startswith(":"):
                keys[depth] = text
                value = rest[1:].lstrip()
                if value.startswith('"') and ((depth == 1 and text in ("type", "subtype")) or (
                        depth == 2 and text == "type" and keys.get(1) == "attachment")):
                    string, _end = _read_string(value, 0)
                    if string is not None:
                        found["attachment_type" if depth == 2 else text] = string
            continue
        index += 1
    return found


def head_census_key(fields: Dict[str, str]) -> str:
    kind = fields.get("type") or ("attachment" if "attachment_type" in fields else "")
    attached = fields.get("attachment_type", "") if kind == mapping.TYPE_ATTACHMENT else ""
    return mapping.KEY_SEPARATOR.join((kind, fields.get("subtype", ""), attached))


def _call_id(head: str) -> Optional[str]:
    found = _TOOL_USE_ID_RE.search(head)
    return found.group(1) if found and _TOOL_RESULT_VALUE in head else None


def stub_events(ctx: ExtractContext, raw: bytes, pos: Pos) -> List[TimelineEvent]:
    head = raw[:STUB_HEAD_BYTES].decode("utf-8", "replace")
    fields = scan_head(head)
    key = head_census_key(fields)
    if mapping.classify(key) == mapping.IGNORED_CLASS:
        return []
    scope = LineScope(ctx, {}, pos)
    call_id = _call_id(head) if fields.get("type") == "user" else None
    if call_id:
        ref = ctx.tools.get(call_id)
        scope.emit(Kind.TOOL_RESULT, {"tool_use_id": call_id, "name": ref.name if ref else None, "bytes": len(raw),
                                      "oversize": True}, parent=ref.call_id if ref else None)
    elif fields.get("type") == "user":
        scope.open_turn()
        scope.emit(Kind.PROMPT, {"origin": ORIGIN_OTHER, "plain": False, "bytes": len(raw), "oversize": True})
    else:
        kind, subtype, attached = (key.split(mapping.KEY_SEPARATOR) + ["", "", ""])[:3]
        scope.emit(Kind.UNKNOWN, {"record_type": ident(kind) or "", "subtype": ident(subtype),
                                  "attachment_type": ident(attached), "bytes": len(raw), "oversize": True})
    return scope.events
