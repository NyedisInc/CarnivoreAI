
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Mapping, Optional

import structlog

from src.core.attention.turn_counts import decode_turn_end_counts
from src.core.timeline import mapping, prompts
from src.core.timeline.context import ExtractContext, LineScope
from src.core.timeline.extract_message import (
    END_NORMAL,
    assistant_record,
    ident,
    learn_inherited,
    notification_events,
    user_record,
)
from src.core.timeline.model import Kind, Pos, TimelineEvent
from src.core.timeline.oversize import OversizeSerialError, stub_events
from src.core.transcript_manifest.tail import line_serial

log = structlog.get_logger()

MAX_LINE_BYTES: int = 5 * 1024 * 1024
VIA_DURATION, VIA_STOP_HOOK = "duration", "stop_hook"

SYSTEM_NOTICE_WHAT: Mapping[str, str] = {
    "api_error": "api_error", "informational": "info", "model_refusal_fallback": "refusal",
    "scheduled_task_fire": "info", "away_summary": "info", "bridge_status": "info", "agents_killed": "info",
}


def _int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _turn_duration(scope: LineScope) -> None:
    record = scope.record
    agents, _present, workflows, _notes = decode_turn_end_counts(record)
    merged = scope.close_turn()
    scope.emit(Kind.TURN_END, {
        "via": VIA_DURATION, "end": END_NORMAL, "duration_ms": _int(record.get("durationMs")),
        "pending_agents": agents, "pending_workflows": workflows, "merged": True if merged else None,
    })


def _stop_hook(scope: LineScope) -> None:
    merged = scope.close_turn()
    scope.emit(Kind.TURN_END, {"via": VIA_STOP_HOOK, "end": END_NORMAL, "merged": True if merged else None})


def _compaction(scope: LineScope) -> None:
    meta = scope.record.get("compactMetadata") if isinstance(scope.record.get("compactMetadata"), dict) else {}
    micro = scope.record.get("subtype") == "microcompact_boundary"
    trigger = "micro" if micro else ident(meta.get("trigger"))
    pre_tokens = _int(meta.get("preTokens"))
    event = scope.emit(Kind.COMPACTION, {"phase": "boundary", "trigger": trigger, "pre_tokens": pre_tokens})
    scope.ctx.compaction_id = event.id


def _local_command(scope: LineScope) -> None:
    text = prompts.text_of(scope.record.get("content"))
    scope.emit(Kind.COMMAND, {"name": ident(prompts.command_name(text)), "part": "invocation", "via": "system"})


def _system_notice(scope: LineScope) -> None:
    record, subtype = scope.record, scope.record.get("subtype")
    error = record.get("error") if isinstance(record.get("error"), dict) else {}
    scope.emit(Kind.NOTICE, {
        "what": SYSTEM_NOTICE_WHAT[subtype], "subtype": ident(subtype),
        "http_status": _int(error.get("status")), "retry_attempt": _int(record.get("retryAttempt")),
    })


def _system_plain(scope: LineScope) -> None:
    scope.emit(Kind.NOTICE, {"what": "hook"})


def _hook_attachment(scope: LineScope) -> None:
    attachment = scope.record["attachment"]
    scope.emit(Kind.NOTICE, {"what": "hook", "subtype": ident(attachment.get("type")),
                             "hook": ident(attachment.get("hookName") or attachment.get("hookEvent")),
                             "exit_code": _int(attachment.get("exitCode"))})


def _queued_command(scope: LineScope) -> None:
    attachment = scope.record["attachment"]
    text = prompts.text_of(attachment.get("prompt"))
    if attachment.get("commandMode") == prompts.ORIGIN_KIND_TASK_NOTICE:
        notification_events(scope, text)
        return
    body, wrapped = prompts.unwrap_pasted(text)
    if scope.ctx.turn is None or scope.ctx.turn_ended:
        scope.open_turn()
    scope.emit(Kind.PROMPT, {"origin": prompts.ORIGIN_QUEUED, "plain": prompts.is_plain(attachment, body),
                             "wrapped": True if wrapped else None, "chars": len(body)})


def _task_status(scope: LineScope) -> None:
    attachment = scope.record["attachment"]
    scope.emit(Kind.NOTICE, {
        "what": "task_notification", "subtype": "task_status", "task_id": ident(attachment.get("taskId")),
        "task_type": ident(attachment.get("taskType")), "status": ident(attachment.get("status")),
    })


def _structured_output(scope: LineScope) -> None:
    attachment = scope.record["attachment"]
    agent = scope.ctx.file_key if scope.thread != "main" else None
    scope.emit(Kind.SUBAGENT_END, {"agent_id": ident(agent), "tool_use_id": ident(attachment.get("toolUseID")),
                                   "status": "completed", "via": "structured_output"})


def _queue_operation(scope: LineScope) -> None:
    record = scope.record
    body, wrapped = prompts.unwrap_pasted(prompts.text_of(record.get("content")))
    scope.emit(Kind.QUEUE, {"op": ident(record.get("operation")), "plain": prompts.is_plain({}, body) if body else None,
                            "wrapped": True if wrapped else None, "chars": len(body) if body else None,
                            "command_uuid": ident(record.get("command_uuid")),
                            "delivery_id": ident(record.get("delivery_id"))})


def _continued_in(scope: LineScope) -> None:
    scope.emit(Kind.CONVERSATION_SWITCH, {"from_conv": ident(scope.ctx.conv), "how": "continued",
                                          "to_conv": ident(scope.record.get("continuedInSessionId"))})


def _suppressed(scope: LineScope) -> None:
    scope.emit(Kind.SUPPRESSED, {"cause": ident(scope.record.get("cause"))})


def _fork_head(scope: LineScope) -> None:
    learn_inherited(scope.ctx, scope.record)
    if scope.ctx.fork_announced or scope.record.get("type") not in ("user", "assistant"):
        return
    scope.ctx.fork_announced = True
    origin = scope.record["forkedFrom"]
    source = origin.get("sessionId") if isinstance(origin, dict) else None
    scope.emit(Kind.CONVERSATION_SWITCH, {"from_conv": ident(source), "to_conv": ident(scope.ctx.conv), "how": "fork"})


HANDLERS: Dict[str, Callable[[LineScope], None]] = {
    "user||": user_record, "assistant||": assistant_record, "queue-operation||": _queue_operation,
    "continued-in||": _continued_in, "history-suppression||": _suppressed,
    "system|turn_duration|": _turn_duration, "system|stop_hook_summary|": _stop_hook,
    "system|compact_boundary|": _compaction, "system|microcompact_boundary|": _compaction,
    "system|local_command|": _local_command, "system||": _system_plain,
    "attachment||queued_command": _queued_command, "attachment||task_status": _task_status,
    "attachment||structured_output": _structured_output,
    **{f"system|{subtype}|": _system_notice for subtype in SYSTEM_NOTICE_WHAT},
    **{key: _hook_attachment for key in mapping.MAPPED if key.startswith("attachment||hook_")},
}


def _unknown(scope: LineScope, key: str) -> None:
    kind, subtype, attached = (key.split(mapping.KEY_SEPARATOR) + ["", "", ""])[:3]
    scope.emit(Kind.UNKNOWN, {
        "record_type": ident(kind) or "", "subtype": ident(subtype), "attachment_type": ident(attached),
    })


def extract_record(ctx: ExtractContext, record: Mapping[str, Any], pos: Pos) -> List[TimelineEvent]:
    scope = LineScope(ctx, record, pos)
    key = mapping.census_key(record)
    verdict = mapping.classify(key)
    if verdict == mapping.UNKNOWN_CLASS:
        log.warning("timeline_unmapped_record", census_key=key, conv=ctx.conv)
        _unknown(scope, key)
    elif verdict == mapping.MAPPED_CLASS:
        if record.get("forkedFrom") is not None:
            _fork_head(scope)
        else:
            HANDLERS[key](scope)
    return scope.events


def extract_line(ctx: ExtractContext, raw: bytes, end_offset: int, *, serial: Optional[str] = None,
                 max_bytes: int = MAX_LINE_BYTES) -> List[TimelineEvent]:
    oversize = len(raw) > max_bytes
    if oversize and not serial:
        raise OversizeSerialError(f"a line of {len(raw)} bytes needs the reader's serial (computing it parses it)")
    pos = Pos(conv=ctx.conv, file_key=ctx.file_key, offset=end_offset, serial=serial or line_serial(raw))
    if oversize:
        return stub_events(ctx, raw, pos)
    try:
        record = json.loads(raw)
    except ValueError:
        record = None
    if not isinstance(record, dict):
        scope = LineScope(ctx, {}, pos)
        scope.emit(Kind.UNKNOWN, {"record_type": "not-json", "bytes": len(raw)})
        return scope.events
    return extract_record(ctx, record, pos)
