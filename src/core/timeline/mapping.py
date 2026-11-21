
from __future__ import annotations

from typing import Any, FrozenSet, Mapping, Tuple

from src.core.timeline.model import Kind
from src.core.transcript_contract.claude_attachment_kinds import ATTACHMENT_KINDS

MAPPED_CLASS: str = "mapped"
IGNORED_CLASS: str = "ignored"
UNKNOWN_CLASS: str = "unknown"

KEY_SEPARATOR: str = "|"

TYPE_ATTACHMENT: str = "attachment"

HOOK_ATTACHMENT_PREFIX: str = "hook_"

_K = Kind

MAPPED: Mapping[str, Tuple[Kind, ...]] = {
    "user||": (_K.PROMPT, _K.COMMAND, _K.TOOL_RESULT, _K.BG_START, _K.TURN_END, _K.COMPACTION, _K.SUBAGENT_END,
               _K.BG_END, _K.NOTICE, _K.CONVERSATION_SWITCH, _K.UNKNOWN),
    "assistant||": (_K.REPLY, _K.THINKING, _K.TOOL_CALL, _K.SUBAGENT_START, _K.TODO, _K.TURN_END, _K.NOTICE,
                    _K.CONVERSATION_SWITCH, _K.UNKNOWN),
    "queue-operation||": (_K.QUEUE,),
    "continued-in||": (_K.CONVERSATION_SWITCH,),
    "history-suppression||": (_K.SUPPRESSED,),
    "system|turn_duration|": (_K.TURN_END,),
    "system|stop_hook_summary|": (_K.TURN_END,),
    "system|compact_boundary|": (_K.COMPACTION,),
    "system|microcompact_boundary|": (_K.COMPACTION,),
    "system|local_command|": (_K.COMMAND,),
    "system|api_error|": (_K.NOTICE,),
    "system|informational|": (_K.NOTICE,),
    "system|model_refusal_fallback|": (_K.NOTICE,),
    "system|scheduled_task_fire|": (_K.NOTICE,),
    "system|away_summary|": (_K.NOTICE,),
    "system|bridge_status|": (_K.NOTICE,),
    "system|agents_killed|": (_K.NOTICE,),
    "system||": (_K.NOTICE,),
    "attachment||queued_command": (_K.PROMPT, _K.SUBAGENT_END, _K.BG_END, _K.NOTICE),
    "attachment||task_status": (_K.NOTICE,),
    "attachment||structured_output": (_K.SUBAGENT_END,),
    **{f"attachment||{name}": (_K.NOTICE,) for name in ATTACHMENT_KINDS if name.startswith(HOOK_ATTACHMENT_PREFIX)},
}

IGNORED: Mapping[str, str] = {
    "progress||": "absent from current files; no rule rests on it",
    "mode||": "state (permission mode), not an event",
    "permission-mode||": "state, not an event",
    "agent-name||": "state (the agent's name)",
    "ai-title||": "state (the title)",
    "custom-title||": "state (the title)",
    "summary||": "legacy title record",
    "last-prompt||": "bookkeeping (the leaf pointer)",
    "cost-state||": "bookkeeping",
    "pr-link||": "state (a link)",
    "frame-link||": "state (a link)",
    "bridge-session||": "state",
    "atis-latch||": "bookkeeping",
    "agent-setting||": "state",
    "session-owner||": "state",
    "tools-used||": "bookkeeping",
    "started||": "sub-agent directory row; the launch and the notice carry the events",
    "result||": "sub-agent directory row; the launch and the notice carry the events",
    "launched||": "sub-agent directory row; the launch and the notice carry the events",
    "failed||": "sub-agent directory row; the end comes from the task notice",
    "fork-context-ref||": "sub-agent head metadata; the thread link is the launch's tool_use_id",
    "attachment||session_cron_carry": "state (cron carried across a restart)",
    "attachment||ultra_effort_enter": "state (effort mode)",
    "attachment||ultra_effort_exit": "state (effort mode)",
    "attachment||workflow_keyword_request": "harness bookkeeping (a workflow keyword was typed)",
    "attachment||peer_mention": "harness bookkeeping",
}

IGNORED_PREFIXES: Tuple[str, ...] = ("file-history-", "api-request", "artifact-")

_REMINDER_KINDS: FrozenSet[str] = frozenset({
    "total_tokens_reminder", "task_reminder", "todo_reminder", "silent_turn_reminder", "batching_reminder_sent",
    "thinking_drop", "thinking_stripped", "read_truncation_notice", "bash_output_audience_note",
})
_CONTEXT_KINDS: FrozenSet[str] = frozenset({
    "agent_listing_delta", "deferred_tools_delta", "deferred_tools_record", "skill_listing", "mcp_instructions_delta",
    "prompt_snapshot", "session_context", "environment", "directory", "instructions", "command_permissions",
    "nested_memory", "invoked_skills", "inlined_image_paths",
})
_FILE_KINDS: FrozenSet[str] = frozenset({
    "edited_text_file", "file", "pdf_reference", "plan_file_reference", "compact_file_reference",
})
_DATE_KINDS: FrozenSet[str] = frozenset({"date", "date_change"})
_STATE_KINDS: FrozenSet[str] = frozenset({
    "model", "plan_mode", "plan_mode_exit", "auto_mode", "auto_mode_exit", "credential_org", "remote_session_change",
})
IGNORED_ATTACHMENT_KINDS: FrozenSet[str] = _REMINDER_KINDS | _CONTEXT_KINDS | _FILE_KINDS | _DATE_KINDS | _STATE_KINDS


def census_key(record: Mapping[str, Any]) -> str:
    kind = record.get("type")
    kind = kind if isinstance(kind, str) else ""
    subtype = record.get("subtype")
    subtype = subtype if isinstance(subtype, str) else ""
    attachment = record.get("attachment")
    attached = attachment.get("type") if isinstance(attachment, dict) and kind == TYPE_ATTACHMENT else ""
    attached = attached if isinstance(attached, str) else ""
    return KEY_SEPARATOR.join((kind, subtype, attached))


def classify(key: str) -> str:
    if key in MAPPED:
        return MAPPED_CLASS
    if key in IGNORED or key.startswith(IGNORED_PREFIXES):
        return IGNORED_CLASS
    parts = key.split(KEY_SEPARATOR)
    if len(parts) == 3 and parts[0] == TYPE_ATTACHMENT and parts[1] == "" and parts[2] in IGNORED_ATTACHMENT_KINDS:
        return IGNORED_CLASS
    return UNKNOWN_CLASS


def mapped_kinds(key: str) -> Tuple[Kind, ...]:
    return MAPPED.get(key, ())

