
from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Optional, Tuple

from src.core.transcript_contract.codex_records import (
    EVENT_MSG_TYPES,
    RESPONSE_ITEM_TYPES,
    CodexLine,
    Compacted,
    SessionMeta,
    TurnContext,
)
from src.core.transcript_contract.fields import (
    EXTRA_KEY,
    MISSING_REQUIRED,
    TYPE_MISMATCH,
    UNKNOWN_TYPE,
    Report,
    bind,
    json_type,
    safe_token,
)
from src.core.transcript_contract.parsed import (
    FAMILY_CODEX,
    STATUS_BLANK,
    STATUS_NON_OBJECT,
    STATUS_OK,
    STATUS_UNPARSEABLE,
    ParsedLine,
    UnknownRecord,
)

PLAIN_PAYLOADS: Dict[str, type] = {
    "session_meta": SessionMeta,
    "turn_context": TurnContext,
    "compacted": Compacted,
}

TYPED_PAYLOADS: Dict[str, Dict[str, type]] = {
    "response_item": RESPONSE_ITEM_TYPES,
    "event_msg": EVENT_MSG_TYPES,
}

ENVELOPE_KEYS: Tuple[str, ...] = ("timestamp", "type", "payload")


def _envelope(obj: Mapping[str, Any], report: Report) -> Tuple[Optional[str], str]:
    ts = obj.get("timestamp")
    if "timestamp" not in obj:
        report.add(MISSING_REQUIRED, "timestamp")
    elif not isinstance(ts, str):
        report.add(TYPE_MISMATCH, "timestamp", json_type(ts))
        ts = None
    for key in obj:
        if key not in ENVELOPE_KEYS:
            report.add(EXTRA_KEY, safe_token(key))
    ltype = obj.get("type")
    return ts, (ltype if isinstance(ltype, str) else "<no-type>")


def _payload(ltype: str, payload: Mapping[str, Any],
             report: Report) -> Tuple[str, Optional[str], Any, bool]:
    if ltype in PLAIN_PAYLOADS:
        return ltype, None, bind(PLAIN_PAYLOADS[ltype], payload, "payload.", report), True
    table = TYPED_PAYLOADS.get(ltype)
    if table is None:
        token = safe_token(ltype)
        report.add(UNKNOWN_TYPE, "codex_line", token)
        return token, None, UnknownRecord(token, payload), False
    raw_ptype = payload.get("type")
    ptype = raw_ptype if isinstance(raw_ptype, str) else "<no-type>"
    cls = table.get(ptype)
    if cls is None:
        token = safe_token(ptype)
        report.add(UNKNOWN_TYPE, f"codex_payload:{ltype}", token)
        return f"{ltype}:{token}", token, UnknownRecord(token, payload), False
    return f"{ltype}:{ptype}", ptype, bind(cls, payload, f"payload[{ptype}].", report), True


def _legacy(obj: Mapping[str, Any], report: Report) -> Tuple[str, Any, bool]:
    if "record_type" in obj:
        rtype = safe_token(obj.get("record_type"))
        return f"legacy:{rtype}", CodexLine(rtype, None, None, UnknownRecord(rtype, obj), True), True
    ptype = obj.get("type")
    if isinstance(ptype, str) and ptype in RESPONSE_ITEM_TYPES:
        record = bind(RESPONSE_ITEM_TYPES[ptype], obj, f"[{ptype}].", report)
        return f"legacy:{ptype}", CodexLine(ptype, None, ptype, record, True), True
    if "id" in obj and "timestamp" in obj and "type" not in obj:
        record = bind(SessionMeta, obj, "", Report())
        return "legacy:session_meta", CodexLine("session_meta", None, None, record, True), True
    token = safe_token(ptype) if ptype is not None else "<no-type>"
    report.add(UNKNOWN_TYPE, "codex_line", token)
    return token, CodexLine(token, None, None, UnknownRecord(token, obj), False), False


def parse_codex_obj(obj: Mapping[str, Any], text: str = "") -> ParsedLine:
    report = Report()
    if "payload" not in obj:
        kind, line, known = _legacy(obj, report)
        return ParsedLine(FAMILY_CODEX, STATUS_OK, kind, line, known, tuple(report.findings),
                          obj, text)
    ts, ltype = _envelope(obj, report)
    payload = obj.get("payload")
    if not isinstance(payload, dict):
        report.add(TYPE_MISMATCH, "payload", json_type(payload))
        line = CodexLine(ltype, ts, None, UnknownRecord(ltype, obj))
        return ParsedLine(FAMILY_CODEX, STATUS_OK, ltype, line, False, tuple(report.findings),
                          obj, text)
    kind, ptype, record, known = _payload(ltype, payload, report)
    line = CodexLine(ltype, ts, ptype, record)
    return ParsedLine(FAMILY_CODEX, STATUS_OK, kind, line, known, tuple(report.findings), obj, text)


def parse_codex_line(text: str) -> ParsedLine:
    body = text.rstrip("\r\n")
    if not body.strip():
        return ParsedLine(FAMILY_CODEX, STATUS_BLANK, text=text)
    try:
        obj = json.loads(body)
    except ValueError:
        return ParsedLine(FAMILY_CODEX, STATUS_UNPARSEABLE, text=text)
    if not isinstance(obj, dict):
        return ParsedLine(FAMILY_CODEX, STATUS_NON_OBJECT, f"<{json_type(obj)}>", text=text)
    return parse_codex_obj(obj, text)
