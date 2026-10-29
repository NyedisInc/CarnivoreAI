
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Union

from src.core.transcript_contract.claude_attachment_kinds import ATTACHMENT_KINDS
from src.core.transcript_contract.fields import (
    ARR,
    BOOL,
    EXTRA_KEY,
    MISSING_REQUIRED,
    OBJ,
    STR,
    TYPE_MISMATCH,
    UNKNOWN_TYPE,
    Report,
    bind,
    jf,
    json_type,
    safe_token,
)


@dataclass(frozen=True, kw_only=True)
class QueuedCommand:

    prompt: Optional[Union[str, List[Any]]] = jf("prompt", ARR + STR, required=True,
                                                 first_seen="2.1.101")
    command_mode: Optional[str] = jf("commandMode", STR, first_seen="2.1.101")
    source_uuid: Optional[str] = jf("source_uuid", STR, first_seen="2.1.101")
    origin: Optional[Mapping[str, Any]] = jf("origin", OBJ, first_seen="2.1.101")
    timestamp: Optional[str] = jf("timestamp", STR, first_seen="2.1.101")
    is_meta: Optional[bool] = jf("isMeta", BOOL, first_seen="2.1.101")
    human_turn: Optional[bool] = jf("humanTurn", BOOL, first_seen="2.1.101")
    image_paste_ids: Optional[List[Any]] = jf("imagePasteIds", ARR, first_seen="2.1.101")
    delivery_id: Optional[str] = jf("delivery_id", STR, first_seen="2.1.101")
    usage: Optional[Mapping[str, Any]] = jf("usage", OBJ, first_seen="2.1.101")


@dataclass(frozen=True)
class AttachmentBody:

    type: str
    known: bool
    raw: Mapping[str, Any]
    queued_command: Optional[QueuedCommand] = None


def _check_kind(kind: str, body: Mapping[str, Any], path: str, report: Report) -> None:
    spec = ATTACHMENT_KINDS[kind]
    where = f"{path.rstrip('.')}[{kind}]."
    for key, (types, required) in spec.keys.items():
        if key not in body:
            if required:
                report.add(MISSING_REQUIRED, where + key)
            continue
        found = json_type(body[key])
        if found not in types:
            report.add(TYPE_MISMATCH, where + key, found)
    for key in body:
        if key != "type" and key not in spec.keys:
            report.add(EXTRA_KEY, where + safe_token(key))


def parse_attachment_body(value: Any, path: str, report: Report) -> AttachmentBody:
    raw_kind = value.get("type")
    if not isinstance(raw_kind, str):
        report.add(MISSING_REQUIRED if raw_kind is None else TYPE_MISMATCH,
                   path + "type", "" if raw_kind is None else json_type(raw_kind))
        return AttachmentBody(type="<no-type>", known=False, raw=value)
    if raw_kind not in ATTACHMENT_KINDS:
        report.add(UNKNOWN_TYPE, "attachment_kind", safe_token(raw_kind))
        return AttachmentBody(type=safe_token(raw_kind), known=False, raw=value)
    queued: Optional[QueuedCommand] = None
    if raw_kind == "queued_command":
        queued = bind(QueuedCommand, value, f"{path.rstrip('.')}[queued_command].", Report())
    _check_kind(raw_kind, value, path, report)
    return AttachmentBody(type=raw_kind, known=True, raw=value, queued_command=queued)
