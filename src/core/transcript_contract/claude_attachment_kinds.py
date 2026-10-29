
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Tuple

from src.core.transcript_contract.fields import ARR, BOOL, INT, NULL, OBJ, STR


@dataclass(frozen=True)
class AttachmentKind:

    first_seen: str
    measured: int
    keys: Mapping[str, Tuple[Tuple[str, ...], bool]]


def _kind(first_seen: str, measured: int,
          keys: Mapping[str, Tuple[Tuple[str, ...], bool]]) -> AttachmentKind:
    return AttachmentKind(first_seen, measured, keys)


ATTACHMENT_KINDS: Dict[str, AttachmentKind] = {
    "agent_listing_delta": _kind("2.1.170", 0, {
        "addedLines": (ARR, True),
        "addedTypes": (ARR, True),
        "builtInTypes": (ARR, False),
        "isInitial": (BOOL, True),
        "removedTypes": (ARR, True),
        "showConcurrencyNote": (BOOL, True),
    }),
    "auto_mode": _kind("2.1.181", 0, {
        "autoModeConsentFlow": (BOOL, False),
        "bashFirst": (BOOL, False),
        "bashFirstSteer": (STR, False),
        "bypass": (BOOL, False),
        "steerOnly": (BOOL, False),
    }),
    "auto_mode_exit": _kind("2.1.278", 0, {
        "bashFirst": (BOOL, True),
        "steerOnly": (BOOL, True),
    }),
    "bash_output_audience_note": _kind("2.1.263", 0, {
        "toolUseID": (STR, True),
    }),
    "batching_reminder_sent": _kind("2.1.263", 0, {
        "clearAt": (STR, False),
        "model": (STR, True),
        "text": (STR, True),
    }),
    "command_permissions": _kind("2.1.111", 0, {
        "allowedTools": (ARR, True),
    }),
    "compact_file_reference": _kind("2.1.111", 0, {
        "displayPath": (STR, True),
        "filename": (STR, True),
    }),
    "credential_org": _kind("2.1.281", 0, {
        "organizationUuid": (STR, True),
    }),
    "date": _kind("2.1.260", 0, {
        "changed": (BOOL, False),
        "date": (STR, True),
    }),
    "date_change": _kind("2.1.111", 0, {
        "newDate": (STR, True),
    }),
    "deferred_tools_delta": _kind("2.1.92", 0, {
        "addedLines": (ARR, True),
        "addedNames": (ARR, True),
        "failedMcpServers": (ARR, False),
        "needsAuthMcpServers": (ARR, False),
        "pendingMcpServers": (ARR, False),
        "readdedNames": (ARR, False),
        "removedNames": (ARR, True),
        "retractedTools": (ARR, False),
        "surfacedDefinitions": (ARR, False),
        "surfacedNames": (ARR, False),
        "wireHiddenNames": (ARR, False),
    }),
    "deferred_tools_record": _kind("2.1.260", 0, {
        "entries": (ARR, True),
        "nameOnlyAnnouncements": (ARR, False),
        "strippedReferences": (ARR, False),
        "toolInputCopies": (ARR, False),
    }),
    "directory": _kind("2.1.209", 0, {
        "content": (STR, True),
        "displayPath": (STR, True),
        "path": (STR, True),
    }),
    "edited_text_file": _kind("2.1.101", 0, {
        "displayPath": (STR, False),
        "filename": (STR, True),
        "snippet": (STR, True),
    }),
    "environment": _kind("2.1.260", 0, {
        "changes": (ARR, False),
        "snapshot": (OBJ, True),
    }),
    "file": _kind("2.1.111", 0, {
        "content": (OBJ, True),
        "displayPath": (STR, True),
        "filename": (STR, True),
    }),
    "hook_additional_context": _kind("2.1.111", 0, {
        "content": (ARR, True),
        "hookEvent": (STR, True),
        "hookName": (STR, True),
        "toolUseID": (STR, True),
    }),
    "hook_cancelled": _kind("2.1.119", 0, {
        "command": (STR, False),
        "durationMs": (INT, False),
        "hookEvent": (STR, True),
        "hookName": (STR, True),
        "toolUseID": (STR, True),
    }),
    "hook_non_blocking_error": _kind("2.1.101", 0, {
        "command": (STR, True),
        "durationMs": (INT, True),
        "exitCode": (INT, True),
        "hookEvent": (STR, True),
        "hookName": (STR, True),
        "stderr": (STR, True),
        "stdout": (STR, True),
        "toolUseID": (STR, True),
    }),
    "hook_permission_decision": _kind("2.1.223", 0, {
        "decision": (STR, True),
        "hookEvent": (STR, True),
        "toolUseID": (STR, True),
    }),
    "hook_success": _kind("2.1.101", 0, {
        "command": (STR, True),
        "content": (STR, True),
        "durationMs": (INT, True),
        "exitCode": (INT, True),
        "hookEvent": (STR, True),
        "hookName": (STR, True),
        "stderr": (STR, True),
        "stdout": (STR, True),
        "toolUseID": (STR, True),
    }),
    "hook_system_message": _kind("2.1.111", 0, {
        "content": (STR, True),
        "hookEvent": (STR, True),
        "hookName": (STR, True),
        "toolUseID": (STR, True),
    }),
    "inlined_image_paths": _kind("2.1.263", 0, {
        "paths": (ARR, True),
    }),
    "instructions": _kind("2.1.260", 0, {
        "changed": (BOOL, False),
        "files": (ARR, True),
        "reason": (STR, False),
        "removed": (ARR, False),
    }),
    "invoked_skills": _kind("2.1.111", 0, {
        "skills": (ARR, True),
    }),
    "mcp_instructions_delta": _kind("2.1.128", 0, {
        "addedBlocks": (ARR, True),
        "addedNames": (ARR, True),
        "removedNames": (ARR, True),
    }),
    "model": _kind("2.1.260", 0, {
        "identity": (OBJ, True),
        "text": (STR, True),
    }),
    "nested_memory": _kind("2.1.138", 0, {
        "content": (OBJ, True),
        "displayPath": (STR, True),
        "path": (STR, True),
    }),
    "pdf_reference": _kind("2.1.154", 0, {
        "displayPath": (STR, True),
        "fileSize": (INT, True),
        "filename": (STR, True),
        "pageCount": (INT, True),
    }),
    "plan_file_reference": _kind("2.1.111", 0, {
        "planContent": (STR, True),
        "planFilePath": (STR, True),
    }),
    "plan_mode": _kind("2.1.165", 0, {
        "isSubAgent": (BOOL, True),
        "planExists": (BOOL, True),
        "planFilePath": (STR, True),
        "reminderType": (STR, True),
    }),
    "plan_mode_exit": _kind("2.1.165", 0, {
        "planExists": (BOOL, True),
        "planFilePath": (STR, True),
    }),
    "prompt_snapshot": _kind("2.1.260", 0, {
        "cliPrefix": (STR, False),
        "contextRendering": (STR, False),
        "echoWireToolInputs": (BOOL, False),
        "hostPrompt": (STR, False),
        "inlineTools": (BOOL, False),
        "keptReminders": (BOOL, False),
        "reminderFold": (BOOL, False),
        "systemPrompt": (ARR, True),
        "systemTurns": (BOOL, False),
        "toolChangeHeader": (BOOL, False),
        "tools": (ARR, False),
    }),
    "queued_command": _kind("2.1.101", 0, {
        "commandMode": (STR, False),
        "delivery_id": (STR, False),
        "humanTurn": (BOOL, False),
        "imagePasteIds": (ARR, False),
        "isMeta": (BOOL, False),
        "origin": (OBJ, False),
        "prompt": (ARR + STR, True),
        "source_uuid": (STR, False),
        "timestamp": (STR, False),
        "usage": (OBJ, False),
    }),
    "read_truncation_notice": _kind("2.1.205", 0, {
        "banner": (STR, True),
        "toolUseID": (STR, True),
    }),
    "remote_session_change": _kind("2.1.255", 0, {
        "commit": (STR, True),
        "managedCommit": (BOOL, False),
        "managedPr": (BOOL, False),
        "pr": (STR, True),
        "sendUserFileHint": (BOOL, True),
        "url": (NULL + STR, True),
    }),
    "session_context": _kind("2.1.260", 0, {
        "changed": (BOOL, False),
        "context": (OBJ, True),
        "reason": (STR, False),
    }),
    "silent_turn_reminder": _kind("2.1.263", 0, {
        "text": (STR, True),
    }),
    "skill_listing": _kind("2.1.101", 0, {
        "content": (STR, True),
        "isInitial": (BOOL, True),
        "names": (ARR, False),
        "skillCount": (INT, True),
    }),
    "task_reminder": _kind("2.1.142", 0, {
        "content": (ARR, True),
        "itemCount": (INT, True),
    }),
    "task_status": _kind("2.1.111", 0, {
        "deltaSummary": (NULL + STR, True),
        "description": (STR, True),
        "outputFilePath": (STR, True),
        "shell": (OBJ, False),
        "status": (STR, True),
        "taskId": (STR, True),
        "taskType": (STR, True),
    }),
    "thinking_drop": _kind("2.1.280", 0, {
        "blockHashes": (ARR, True),
        "clientChange": (OBJ, True),
        "firstReportForThreadInProcess": (BOOL, True),
        "model": (STR, True),
        "newlyDropped": (OBJ, True),
        "querySource": (STR, True),
        "requestId": (STR, True),
        "thinkingBlocksSent": (INT, True),
        "thinkingTurnsSent": (INT, True),
    }),
    "thinking_stripped": _kind("2.1.263", 0, {
        "scope": (STR, True),
    }),
    "todo_reminder": _kind("2.1.101", 0, {
        "content": (ARR, True),
        "itemCount": (INT, True),
    }),
    "total_tokens_reminder": _kind("2.1.223", 0, {
        "text": (STR, True),
    }),
}
