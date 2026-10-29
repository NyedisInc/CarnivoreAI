
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

SERIALIZER_STYLES: Tuple[Tuple[str, Tuple[str, str], bool], ...] = (
    ("compact", (",", ":"), False),
    ("compact_ascii", (",", ":"), True),
    ("spaced", (", ", ": "), False),
    ("spaced_ascii", (", ", ": "), True),
)

STYLE_NAMES: Tuple[str, ...] = tuple(name for name, _, _ in SERIALIZER_STYLES)

_STYLE_BY_NAME: Dict[str, Tuple[Tuple[str, str], bool]] = {
    name: (seps, ensure_ascii) for name, seps, ensure_ascii in SERIALIZER_STYLES
}

APPEARANCE_KEYS: Tuple[str, ...] = ("isSidechain", "agentId")

KEY_ORDER_NOT_AN_OBJECT: str = "__not_an_object__"

COMPACT_SUBTYPE_BOUNDARY: str = "compact_boundary"
COMPACT_SUBTYPE_SUMMARY: str = "isCompactSummary"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def render_with_style(value: Any, style: str) -> str:
    separators, ensure_ascii = _STYLE_BY_NAME[style]
    return json.dumps(value, separators=separators, ensure_ascii=ensure_ascii)


def detect_style(value: Any, original: str) -> Optional[str]:
    """Find which style, if any, reproduces ``original`` exactly.

    Description: tries each registered style in order and returns the
      first whose output is byte-identical to the original line. Returns
      None when none of them do - the third outcome, which the caller
      must handle by storing the raw line rather than by picking a style
      that does not actually work.
    Inputs: value (the parsed JSON value), original (str - the line's
      exact text, without its trailing newline).
    Output: str (a style name) or None.
    Example: detect_style({"a": 1}, '{"a":1}') -> "compact"
    """
    for name in STYLE_NAMES:
        if render_with_style(value, name) == original:
            return name
    return None


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def stored_body_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class SplitRecord:

    body: Any
    envelope: Dict[str, Any]
    key_order: Any
    body_sha256: str
    body_bytes_sha256: str


def split_record(value: Any) -> SplitRecord:
    if not isinstance(value, dict):
        return SplitRecord(
            body=value, envelope={}, key_order=KEY_ORDER_NOT_AN_OBJECT,
            body_sha256=sha256_text(canonical_json(value)),
            body_bytes_sha256=sha256_text(stored_body_json(value)),
        )
    body: Dict[str, Any] = {}
    envelope: Dict[str, Any] = {}
    for key, item in value.items():
        if key in APPEARANCE_KEYS:
            envelope[key] = item
        else:
            body[key] = item
    return SplitRecord(
        body=body, envelope=envelope, key_order=list(value.keys()),
        body_sha256=sha256_text(canonical_json(body)),
        body_bytes_sha256=sha256_text(stored_body_json(body)),
    )


def reassemble(body: Any, envelope: Dict[str, Any], key_order: Any) -> Any:
    if key_order == KEY_ORDER_NOT_AN_OBJECT:
        return body
    out: Dict[str, Any] = {}
    for key in key_order:
        if key in envelope:
            out[key] = envelope[key]
        elif isinstance(body, dict) and key in body:
            out[key] = body[key]
        else:
            raise KeyError(
                f"key_order names {key!r} but neither the stored body nor "
                "the stored envelope holds it - the stored row is "
                "incomplete, not merely out of order"
            )
    return out


def render_line(
    body: Any, envelope: Dict[str, Any], key_order: Any, style: str,
) -> str:
    return render_with_style(reassemble(body, envelope, key_order), style)


def identity_key(message_uuid: Optional[str], body_sha256: str) -> str:
    return f"{message_uuid or ''}:{body_sha256}"


def parse_line(text: str) -> Tuple[str, Any]:
    if text.strip() == "":
        return "blank", None
    try:
        return "ok", json.loads(text)
    except json.JSONDecodeError:
        return "invalid_json", None


def scalar_fields(body: Any) -> Dict[str, Any]:
    empty = {
        "record_type": None, "role": None, "model": None,
        "compact_subtype": None, "parent_uuid": None, "ts": None,
        "origin_session_ref": None, "message_uuid": None,
        "is_compact_boundary": 0,
    }
    if not isinstance(body, dict):
        return empty
    inner = body.get("message")
    inner = inner if isinstance(inner, dict) else {}

    def _s(value: Any) -> Optional[str]:
        return value if isinstance(value, str) else None

    subtype = _s(body.get("subtype"))
    if subtype == COMPACT_SUBTYPE_BOUNDARY:
        compact_subtype = COMPACT_SUBTYPE_BOUNDARY
    elif body.get("isCompactSummary") is True:
        compact_subtype = COMPACT_SUBTYPE_SUMMARY
    else:
        compact_subtype = None
    return {
        "record_type": _s(body.get("type")),
        "role": _s(inner.get("role")),
        "model": _s(inner.get("model")),
        "compact_subtype": compact_subtype,
        "parent_uuid": _s(body.get("parentUuid")),
        "ts": _s(body.get("timestamp")),
        "origin_session_ref": _s(body.get("sessionId")),
        "message_uuid": _s(body.get("uuid")),
        "is_compact_boundary": 1 if compact_subtype else 0,
    }


AGENT_REF_PREFIXES: Tuple[str, ...] = ("agent:", "agent-")

_CANONICAL_UUID = re.compile(
    r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)

UUID_SCHEME: str = "uuid"
AGENT_SCHEME: str = "agent"

OPAQUE_SCHEME: str = "opaque"

SESSION_REF_SCHEMES: Tuple[str, ...] = (UUID_SCHEME, AGENT_SCHEME, OPAQUE_SCHEME)


def session_ref_scheme(session_ref: str) -> str:
    if any(session_ref.startswith(p) for p in AGENT_REF_PREFIXES):
        return AGENT_SCHEME
    if _CANONICAL_UUID.match(session_ref):
        return UUID_SCHEME
    return OPAQUE_SCHEME


def split_lines(text: str) -> Tuple[List[str], bool]:
    if text == "":
        return [], False
    has_trailing = text.endswith("\n")
    body = text[:-1] if has_trailing else text
    return body.split("\n"), has_trailing


def join_lines(lines: Sequence[str], has_trailing_newline: bool) -> str:
    if not lines:
        return ""
    return "\n".join(lines) + ("\n" if has_trailing_newline else "")
