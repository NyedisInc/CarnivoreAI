
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

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

def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def render_with_style(value: Any, style: str) -> str:
    separators, ensure_ascii = _STYLE_BY_NAME[style]
    return json.dumps(value, separators=separators, ensure_ascii=ensure_ascii)


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
