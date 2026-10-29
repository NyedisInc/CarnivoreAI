
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional

from src.core.transcript_contract.claude_attachments import AttachmentBody, parse_attachment_body
from src.core.transcript_contract.claude_message import (
    AssistantMessage,
    UserMessage,
    parse_assistant_message,
    parse_user_message,
)
from src.core.transcript_contract.fields import ARR, BOOL, INT, NULL, NUM, OBJ, STR, jf


@dataclass(frozen=True, kw_only=True)
class Envelope:

    type: Optional[str] = jf("type", STR, required=True, first_seen="1.0.61")
    uuid: Optional[str] = jf("uuid", STR, required=True, first_seen="1.0.61")
    parent_uuid: Optional[str] = jf("parentUuid", NULL + STR, required=True, first_seen="1.0.61")
    timestamp: Optional[str] = jf("timestamp", STR, required=True, first_seen="1.0.61")
    session_id: Optional[str] = jf("sessionId", STR, required=True, first_seen="1.0.61")
    is_sidechain: Optional[bool] = jf("isSidechain", BOOL, required=True, first_seen="1.0.61")
    user_type: Optional[str] = jf("userType", STR, required=True, first_seen="1.0.61")
    cwd: Optional[str] = jf("cwd", STR, required=True, first_seen="1.0.61")
    version: Optional[str] = jf("version", STR, required=True, first_seen="1.0.61")
    git_branch: Optional[str] = jf("gitBranch", STR, required=True, first_seen="1.0.61")
    agent_id: Optional[str] = jf("agentId", STR, first_seen="2.0.67")
    slug: Optional[str] = jf("slug", STR, first_seen="2.0.64")
    entrypoint: Optional[str] = jf("entrypoint", STR, first_seen="2.1.78")
    forked_from: Optional[Mapping[str, Any]] = jf("forkedFrom", OBJ, first_seen="2.1.17")
    session_id_snake: Optional[str] = jf("session_id", STR, first_seen="2.1.199")


@dataclass(frozen=True, kw_only=True)
class AssistantRecord(Envelope):

    advisor_model: Optional[str] = jf("advisorModel", STR, first_seen="2.1.275")
    api_block_index: Optional[int] = jf("apiBlockIndex", INT, first_seen="2.1.255")
    api_error: Optional[str] = jf("apiError", STR, first_seen="2.1.19")
    api_error_status: Optional[int] = jf("apiErrorStatus", INT, first_seen="2.1.111")
    attribution_agent: Optional[str] = jf("attributionAgent", STR, first_seen="2.1.121")
    attribution_mcp_server: Optional[str] = jf("attributionMcpServer", STR, first_seen="2.1.149")
    attribution_mcp_tool: Optional[str] = jf("attributionMcpTool", STR, first_seen="2.1.149")
    attribution_plugin: Optional[str] = jf("attributionPlugin", STR, first_seen="2.1.128")
    attribution_skill: Optional[str] = jf("attributionSkill", STR, first_seen="2.1.121")
    effort: Optional[str] = jf("effort", STR, first_seen="2.1.215")
    error: Optional[str] = jf("error", STR, first_seen="2.0.64")
    is_aborted_mid_stream: Optional[bool] = jf("isAbortedMidStream", BOOL, first_seen="2.1.229")
    is_api_error_message: Optional[bool] = jf("isApiErrorMessage", BOOL, first_seen="1.0.63")
    message: Optional[AssistantMessage] = jf(
        "message", OBJ, required=True, first_seen="1.0.62", nested=parse_assistant_message)
    per_turn_effort: Optional[str] = jf("perTurnEffort", NULL + STR, first_seen="2.1.275")
    request_id: Optional[str] = jf("requestId", STR, first_seen="1.0.62")
    server_classifier_request: Optional[str] = jf(
        "serverClassifierRequest", STR, first_seen="2.1.278")
    supersedes_uuids: Optional[List[Any]] = jf("supersedesUuids", ARR, first_seen="2.1.209")
    wire_tool_inputs: Optional[Mapping[str, Any]] = jf("wireToolInputs", OBJ, first_seen="2.1.266")


@dataclass(frozen=True, kw_only=True)
class UserRecord(Envelope):

    classifier_boundary: Optional[bool] = jf("classifierBoundary", BOOL, first_seen="2.1.282")
    classifier_meta_lines: Optional[str] = jf("classifierMetaLines", STR, first_seen="2.1.209")
    image_paste_ids: Optional[List[Any]] = jf("imagePasteIds", ARR, first_seen="2.0.76")
    interrupted_by_shutdown: Optional[bool] = jf(
        "interruptedByShutdown", BOOL, first_seen="2.1.219")
    interrupted_message_id: Optional[str] = jf("interruptedMessageId", STR, first_seen="2.1.259")
    is_compact_summary: Optional[bool] = jf("isCompactSummary", BOOL, first_seen="1.0.61")
    is_meta: Optional[bool] = jf("isMeta", BOOL, first_seen="1.0.69")
    is_visible_in_transcript_only: Optional[bool] = jf(
        "isVisibleInTranscriptOnly", BOOL, first_seen="2.0.64")
    mcp_meta: Optional[Mapping[str, Any]] = jf("mcpMeta", OBJ, first_seen="2.1.121")
    message: Optional[UserMessage] = jf(
        "message", OBJ, required=True, first_seen="1.0.61", nested=parse_user_message)
    origin: Optional[Mapping[str, Any]] = jf("origin", OBJ, first_seen="2.1.83")
    permission_mode: Optional[str] = jf("permissionMode", STR, first_seen="2.1.15")
    plan_content: Optional[str] = jf("planContent", STR, first_seen="2.1.20")
    prompt_id: Optional[str] = jf("promptId", STR, first_seen="2.1.71")
    prompt_source: Optional[str] = jf("promptSource", STR, first_seen="2.1.161")
    queue_origin: Optional[Mapping[str, Any]] = jf("queueOrigin", OBJ, first_seen="2.1.284")
    queue_priority: Optional[str] = jf("queuePriority", STR, first_seen="2.1.283")
    queue_skip_attachments: Optional[bool] = jf("queueSkipAttachments", BOOL, first_seen="2.1.247")
    queue_transcript_only: Optional[bool] = jf("queueTranscriptOnly", BOOL, first_seen="2.1.280")
    scheduled_fire_id: Optional[str] = jf("scheduledFireId", STR, first_seen="2.1.283")
    scheduled_task_id: Optional[str] = jf("scheduledTaskId", STR, first_seen="2.1.283")
    server_classifier_context: Optional[Mapping[str, Any]] = jf(
        "serverClassifierContext", OBJ, first_seen="2.1.280")
    source_tool_assistant_uuid: Optional[str] = jf(
        "sourceToolAssistantUUID", STR, first_seen="2.1.1")
    source_tool_use_id: Optional[str] = jf("sourceToolUseID", STR, first_seen="2.0.75")
    thinking_metadata: Optional[Mapping[str, Any]] = jf(
        "thinkingMetadata", OBJ, first_seen="2.0.1")
    todos: Optional[List[Any]] = jf("todos", ARR, first_seen="2.0.64")
    tool_denial_kind: Optional[str] = jf("toolDenialKind", STR, first_seen="2.1.202")
    tool_ends_turn: Optional[bool] = jf("toolEndsTurn", BOOL, first_seen="2.1.187")
    tool_use_result: Optional[List[Any] | Mapping[str, Any] | str] = jf(
        "toolUseResult", ARR + OBJ + STR, first_seen="1.0.62")
    turn_companion: Optional[bool] = jf("turnCompanion", BOOL, first_seen="2.1.237")
    turn_origin: Optional[str] = jf("turnOrigin", STR, first_seen="2.1.278")


@dataclass(frozen=True, kw_only=True)
class SystemRecord(Envelope):

    api_refusal_category: Optional[str] = jf("apiRefusalCategory", STR, first_seen="2.1.197")
    api_refusal_explanation: Optional[str] = jf(
        "apiRefusalExplanation", NULL + STR, first_seen="2.1.197")
    cause: Optional[Mapping[str, Any]] = jf("cause", OBJ, first_seen="2.1.111")
    command_run: Optional[Mapping[str, Any]] = jf("commandRun", OBJ, first_seen="2.1.280")
    compact_metadata: Optional[Mapping[str, Any]] = jf("compactMetadata", OBJ, first_seen="2.0.64")
    content: Optional[str] = jf("content", STR, first_seen="1.0.61")
    cron: Optional[str] = jf("cron", STR, first_seen="2.1.283")
    direction: Optional[str] = jf("direction", STR, first_seen="2.1.197")
    duration_ms: Optional[int] = jf("durationMs", INT, first_seen="2.1.1")
    error: Optional[Mapping[str, Any]] = jf("error", OBJ, first_seen="2.1.4")
    fallback_model: Optional[str] = jf("fallbackModel", STR, first_seen="2.1.197")
    has_output: Optional[bool] = jf("hasOutput", BOOL, first_seen="2.1.15")
    hook_additional_context: Optional[List[Any]] = jf(
        "hookAdditionalContext", ARR, first_seen="2.1.165")
    hook_count: Optional[int] = jf("hookCount", INT, first_seen="2.1.15")
    hook_errors: Optional[List[Any]] = jf("hookErrors", ARR, first_seen="2.1.15")
    hook_infos: Optional[List[Any]] = jf("hookInfos", ARR, first_seen="2.1.15")
    is_meta: Optional[bool] = jf("isMeta", BOOL, first_seen="1.0.61")
    level: Optional[str] = jf("level", STR, first_seen="1.0.61")
    logical_parent_uuid: Optional[str] = jf("logicalParentUuid", STR, first_seen="2.0.64")
    max_retries: Optional[int] = jf("maxRetries", INT, first_seen="2.1.4")
    message_count: Optional[int] = jf("messageCount", INT, first_seen="2.1.83")
    microcompact_metadata: Optional[Mapping[str, Any]] = jf(
        "microcompactMetadata", OBJ, first_seen="2.1.12")
    neutralized_by_fork: Optional[bool] = jf("neutralizedByFork", BOOL, first_seen="2.1.281")
    original_model: Optional[str] = jf("originalModel", STR, first_seen="2.1.197")
    pending_background_agent_count: Optional[int] = jf(
        "pendingBackgroundAgentCount", INT, first_seen="2.1.246")
    prevented_continuation: Optional[bool] = jf("preventedContinuation", BOOL, first_seen="2.1.15")
    prompt: Optional[str] = jf("prompt", STR, first_seen="2.1.283")
    refused_user_message_uuid: Optional[str] = jf(
        "refusedUserMessageUuid", NULL + STR, first_seen="2.1.197")
    request_id: Optional[str] = jf("requestId", STR, first_seen="2.1.197")
    retracted_message_uuids: Optional[List[Any]] = jf(
        "retractedMessageUuids", ARR, first_seen="2.1.197")
    retry_attempt: Optional[int] = jf("retryAttempt", INT, first_seen="2.1.4")
    retry_in_ms: Optional[float] = jf("retryInMs", INT + NUM, first_seen="2.1.4")
    scope: Optional[str] = jf("scope", STR, first_seen="2.1.227")
    source: Optional[str] = jf("source", STR, first_seen="2.1.215")
    stop_reason: Optional[str] = jf("stopReason", STR, first_seen="2.1.15")
    subtype: Optional[str] = jf("subtype", STR, first_seen="2.0.64")
    task_id: Optional[str] = jf("taskId", STR, first_seen="2.1.283")
    tool_use_id: Optional[str] = jf("toolUseID", STR, first_seen="1.0.61")
    trigger: Optional[str] = jf("trigger", STR, first_seen="2.1.197")
    url: Optional[str] = jf("url", STR, first_seen="2.1.246")


@dataclass(frozen=True, kw_only=True)
class AttachmentRecord(Envelope):

    attachment: Optional[AttachmentBody] = jf(
        "attachment", OBJ, required=True, first_seen="2.1.92", nested=parse_attachment_body)
    rendered: Optional[List[Any]] = jf("rendered", ARR, first_seen="2.1.260")
    rendered_in_human_turn: Optional[List[Any]] = jf(
        "renderedInHumanTurn", ARR, first_seen="2.1.263")
    rendered_role: Optional[str] = jf("renderedRole", STR, first_seen="2.1.285")


@dataclass(frozen=True, kw_only=True)
class ProgressRecord(Envelope):

    data: Optional[Mapping[str, Any]] = jf("data", OBJ, required=True, first_seen="2.1.12")
    parent_tool_use_id: Optional[str] = jf(
        "parentToolUseID", STR, required=True, first_seen="2.1.12")
    tool_use_id: Optional[str] = jf("toolUseID", STR, required=True, first_seen="2.1.12")


