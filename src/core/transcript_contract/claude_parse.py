
from __future__ import annotations

import json
from typing import Any, Dict, Mapping

from src.core.transcript_contract import claude_meta_records as meta
from src.core.transcript_contract.claude_records import (
    AssistantRecord,
    AttachmentRecord,
    ProgressRecord,
    SystemRecord,
    UserRecord,
)
from src.core.transcript_contract.fields import (
    MISSING_REQUIRED,
    TYPE_MISMATCH,
    UNKNOWN_TYPE,
    Report,
    bind,
    json_type,
    safe_token,
)
from src.core.transcript_contract.parsed import (
    FAMILY_CLAUDE,
    STATUS_BLANK,
    STATUS_NON_OBJECT,
    STATUS_OK,
    STATUS_UNPARSEABLE,
    ParsedLine,
    UnknownRecord,
)

CLAUDE_RECORD_TYPES: Dict[str, type] = {
    "assistant": AssistantRecord,
    "user": UserRecord,
    "system": SystemRecord,
    "attachment": AttachmentRecord,
    "progress": ProgressRecord,
    "agent-name": meta.AgentNameRecord,
    "ai-title": meta.AiTitleRecord,
    "artifact-autoreact-ledger": meta.ArtifactAutoreactLedgerRecord,
    "artifact-comment-monitor": meta.ArtifactCommentMonitorRecord,
    "atis-latch": meta.AtisLatchRecord,
    "bridge-session": meta.BridgeSessionRecord,
    "cost-state": meta.CostStateRecord,
    "custom-title": meta.CustomTitleRecord,
    "file-history-delta": meta.FileHistoryDeltaRecord,
    "file-history-snapshot": meta.FileHistorySnapshotRecord,
    "fork-context-ref": meta.ForkContextRefRecord,
    "frame-link": meta.FrameLinkRecord,
    "history-suppression": meta.HistorySuppressionRecord,
    "last-prompt": meta.LastPromptRecord,
    "mode": meta.ModeRecord,
    "permission-mode": meta.PermissionModeRecord,
    "pr-link": meta.PrLinkRecord,
    "queue-operation": meta.QueueOperationRecord,
    "summary": meta.SummaryRecord,
    "started": meta.WorkflowStartedRecord,
    "result": meta.WorkflowResultRecord,
}

SYSTEM_SUBTYPES: Dict[str, str] = {
    "api_error": "2.1.4",
    "away_summary": "2.1.199",
    "bridge_status": "2.1.246",
    "compact_boundary": "2.0.64",
    "informational": "2.1.101",
    "local_command": "2.0.76",
    "microcompact_boundary": "2.1.12",
    "model_refusal_fallback": "2.1.197",
    "scheduled_task_fire": "2.1.283",
    "stop_hook_summary": "2.1.15",
    "turn_duration": "2.1.1",
}

QUEUE_OPERATIONS: frozenset = frozenset({"enqueue", "dequeue", "remove", "popAll"})


def _check_discriminators(kind: str, obj: Mapping[str, Any], report: Report) -> None:
    if kind == "system":
        sub = obj.get("subtype")
        if isinstance(sub, str) and sub not in SYSTEM_SUBTYPES:
            report.add(UNKNOWN_TYPE, "system_subtype", safe_token(sub))
    elif kind == "queue-operation":
        op = obj.get("operation")
        if isinstance(op, str) and op not in QUEUE_OPERATIONS:
            report.add(UNKNOWN_TYPE, "queue_operation", safe_token(op))


def parse_claude_obj(obj: Mapping[str, Any], text: str = "") -> ParsedLine:
    report = Report()
    raw_kind = obj.get("type")
    if not isinstance(raw_kind, str):
        report.add(MISSING_REQUIRED if raw_kind is None else TYPE_MISMATCH, "type",
                   "" if raw_kind is None else json_type(raw_kind))
        return ParsedLine(FAMILY_CLAUDE, STATUS_OK, "<no-type>", UnknownRecord("<no-type>", obj),
                          False, tuple(report.findings), obj, text)
    cls = CLAUDE_RECORD_TYPES.get(raw_kind)
    if cls is None:
        token = safe_token(raw_kind)
        report.add(UNKNOWN_TYPE, "record", token)
        return ParsedLine(FAMILY_CLAUDE, STATUS_OK, token, UnknownRecord(token, obj), False,
                          tuple(report.findings), obj, text)
    record = bind(cls, obj, "", report)
    _check_discriminators(raw_kind, obj, report)
    return ParsedLine(FAMILY_CLAUDE, STATUS_OK, raw_kind, record, True, tuple(report.findings),
                      obj, text)


def parse_claude_line(text: str) -> ParsedLine:
    body = text.rstrip("\r\n")
    if not body.strip():
        return ParsedLine(FAMILY_CLAUDE, STATUS_BLANK, text=text)
    try:
        obj = json.loads(body)
    except ValueError:
        return ParsedLine(FAMILY_CLAUDE, STATUS_UNPARSEABLE, text=text)
    if not isinstance(obj, dict):
        return ParsedLine(FAMILY_CLAUDE, STATUS_NON_OBJECT, f"<{json_type(obj)}>", text=text)
    return parse_claude_obj(obj, text)
