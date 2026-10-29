
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Union

from src.core.transcript_contract.fields import ARR, BOOL, INT, NULL, OBJ, STR, Report, bind, jf

V = "0.115"
"""The Codex CLI line measured (prerelease builds of 0.115)."""



@dataclass(frozen=True, kw_only=True)
class SessionMeta:

    id: Optional[str] = jf("id", STR, required=True, first_seen=V)
    timestamp: Optional[str] = jf("timestamp", STR, required=True, first_seen=V)
    cwd: Optional[str] = jf("cwd", STR, required=True, first_seen=V)
    cli_version: Optional[str] = jf("cli_version", STR, required=True, first_seen=V)
    originator: Optional[str] = jf("originator", STR, first_seen=V)
    source: Optional[Union[str, Mapping[str, Any]]] = jf("source", STR + OBJ, first_seen=V)
    model_provider: Optional[str] = jf("model_provider", STR, first_seen=V)
    base_instructions: Optional[Mapping[str, Any]] = jf("base_instructions", OBJ, first_seen=V)
    dynamic_tools: Optional[List[Any]] = jf("dynamic_tools", ARR, first_seen=V)
    instructions: Optional[str] = jf("instructions", STR + NULL)
    git: Optional[Mapping[str, Any]] = jf("git", OBJ + NULL)


@dataclass(frozen=True, kw_only=True)
class TurnContext:

    cwd: Optional[str] = jf("cwd", STR, required=True, first_seen=V)
    model: Optional[str] = jf("model", STR, required=True, first_seen=V)
    turn_id: Optional[str] = jf("turn_id", STR, first_seen=V)
    approval_policy: Optional[str] = jf("approval_policy", STR, first_seen=V)
    sandbox_policy: Optional[Mapping[str, Any]] = jf("sandbox_policy", OBJ, first_seen=V)
    effort: Optional[str] = jf("effort", STR + NULL, first_seen=V)
    summary: Optional[str] = jf("summary", STR, first_seen=V)
    collaboration_mode: Optional[Mapping[str, Any]] = jf("collaboration_mode", OBJ, first_seen=V)
    current_date: Optional[str] = jf("current_date", STR, first_seen=V)
    timezone: Optional[str] = jf("timezone", STR, first_seen=V)
    personality: Optional[str] = jf("personality", STR, first_seen=V)
    realtime_active: Optional[bool] = jf("realtime_active", BOOL, first_seen=V)
    truncation_policy: Optional[Mapping[str, Any]] = jf("truncation_policy", OBJ, first_seen=V)
    developer_instructions: Optional[str] = jf("developer_instructions", STR, first_seen=V)
    user_instructions: Optional[str] = jf("user_instructions", STR, first_seen=V)


@dataclass(frozen=True, kw_only=True)
class Compacted:

    message: Optional[str] = jf("message", STR, required=True, first_seen=V)
    replacement_history: Optional[List[Any]] = jf("replacement_history", ARR, first_seen=V)



@dataclass(frozen=True, kw_only=True)
class RiMessage:

    type: Optional[str] = jf("type", STR, required=True, first_seen=V)
    role: Optional[str] = jf("role", STR, required=True, first_seen=V)
    content: Optional[List[Any]] = jf("content", ARR, required=True, first_seen=V)
    phase: Optional[str] = jf("phase", STR, first_seen=V)
    id: Optional[str] = jf("id", STR)


@dataclass(frozen=True, kw_only=True)
class RiReasoning:

    type: Optional[str] = jf("type", STR, required=True, first_seen=V)
    summary: Optional[List[Any]] = jf("summary", ARR, required=True, first_seen=V)
    content: Optional[List[Any]] = jf("content", ARR + NULL, first_seen=V)
    encrypted_content: Optional[str] = jf("encrypted_content", STR + NULL, first_seen=V)
    id: Optional[str] = jf("id", STR)


@dataclass(frozen=True, kw_only=True)
class RiFunctionCall:

    type: Optional[str] = jf("type", STR, required=True, first_seen=V)
    name: Optional[str] = jf("name", STR, required=True, first_seen=V)
    arguments: Optional[str] = jf("arguments", STR, required=True, first_seen=V)
    call_id: Optional[str] = jf("call_id", STR, required=True, first_seen=V)
    id: Optional[str] = jf("id", STR)


@dataclass(frozen=True, kw_only=True)
class RiFunctionCallOutput:

    type: Optional[str] = jf("type", STR, required=True, first_seen=V)
    call_id: Optional[str] = jf("call_id", STR, required=True, first_seen=V)
    output: Optional[Union[str, Mapping[str, Any], List[Any]]] = jf(
        "output", STR + OBJ + ARR, required=True, first_seen=V)


@dataclass(frozen=True, kw_only=True)
class RiCustomToolCall:

    type: Optional[str] = jf("type", STR, required=True, first_seen=V)
    name: Optional[str] = jf("name", STR, required=True, first_seen=V)
    input: Optional[str] = jf("input", STR, required=True, first_seen=V)
    call_id: Optional[str] = jf("call_id", STR, required=True, first_seen=V)
    status: Optional[str] = jf("status", STR, first_seen=V)
    id: Optional[str] = jf("id", STR)


@dataclass(frozen=True, kw_only=True)
class RiCustomToolCallOutput:

    type: Optional[str] = jf("type", STR, required=True, first_seen=V)
    call_id: Optional[str] = jf("call_id", STR, required=True, first_seen=V)
    output: Optional[Union[str, Mapping[str, Any], List[Any]]] = jf(
        "output", STR + OBJ + ARR, required=True, first_seen=V)


@dataclass(frozen=True, kw_only=True)
class RiWebSearchCall:

    type: Optional[str] = jf("type", STR, required=True, first_seen=V)
    status: Optional[str] = jf("status", STR, first_seen=V)
    action: Optional[Mapping[str, Any]] = jf("action", OBJ, first_seen=V)
    id: Optional[str] = jf("id", STR)


@dataclass(frozen=True, kw_only=True)
class RiLocalShellCall:

    type: Optional[str] = jf("type", STR, required=True)
    call_id: Optional[str] = jf("call_id", STR + NULL)
    status: Optional[str] = jf("status", STR)
    action: Optional[Mapping[str, Any]] = jf("action", OBJ)
    id: Optional[str] = jf("id", STR + NULL)


@dataclass(frozen=True, kw_only=True)
class RiGhostSnapshot:

    type: Optional[str] = jf("type", STR, required=True)
    ghost_commit: Optional[Mapping[str, Any]] = jf("ghost_commit", OBJ)



@dataclass(frozen=True, kw_only=True)
class TokenCountInfo:

    total_token_usage: Optional[Mapping[str, Any]] = jf("total_token_usage", OBJ, required=True,
                                                         first_seen=V)
    last_token_usage: Optional[Mapping[str, Any]] = jf("last_token_usage", OBJ, required=True,
                                                        first_seen=V)
    model_context_window: Optional[int] = jf("model_context_window", INT + NULL, first_seen=V)


def _token_info(value: Any, path: str, report: Report) -> TokenCountInfo:
    return bind(TokenCountInfo, value, path, report)


@dataclass(frozen=True, kw_only=True)
class EvTokenCount:

    type: Optional[str] = jf("type", STR, required=True, first_seen=V)
    info: Optional[TokenCountInfo] = jf("info", OBJ + NULL, first_seen=V, nested=_token_info)
    rate_limits: Optional[Mapping[str, Any]] = jf("rate_limits", OBJ + NULL, first_seen=V)


@dataclass(frozen=True, kw_only=True)
class EvAgentMessage:

    type: Optional[str] = jf("type", STR, required=True, first_seen=V)
    message: Optional[str] = jf("message", STR, required=True, first_seen=V)
    phase: Optional[str] = jf("phase", STR, first_seen=V)


@dataclass(frozen=True, kw_only=True)
class EvUserMessage:

    type: Optional[str] = jf("type", STR, required=True, first_seen=V)
    message: Optional[str] = jf("message", STR, required=True, first_seen=V)
    images: Optional[List[Any]] = jf("images", ARR + NULL, first_seen=V)
    local_images: Optional[List[Any]] = jf("local_images", ARR, first_seen=V)
    text_elements: Optional[List[Any]] = jf("text_elements", ARR, first_seen=V)


@dataclass(frozen=True, kw_only=True)
class EvTaskStarted:

    type: Optional[str] = jf("type", STR, required=True, first_seen=V)
    turn_id: Optional[str] = jf("turn_id", STR, first_seen=V)
    model_context_window: Optional[int] = jf("model_context_window", INT + NULL, first_seen=V)
    collaboration_mode_kind: Optional[str] = jf("collaboration_mode_kind", STR, first_seen=V)


@dataclass(frozen=True, kw_only=True)
class EvTaskComplete:

    type: Optional[str] = jf("type", STR, required=True, first_seen=V)
    turn_id: Optional[str] = jf("turn_id", STR, first_seen=V)
    last_agent_message: Optional[str] = jf("last_agent_message", STR + NULL, first_seen=V)


@dataclass(frozen=True, kw_only=True)
class EvContextCompacted:

    type: Optional[str] = jf("type", STR, required=True, first_seen=V)


@dataclass(frozen=True, kw_only=True)
class EvItemCompleted:

    type: Optional[str] = jf("type", STR, required=True, first_seen=V)
    thread_id: Optional[str] = jf("thread_id", STR, first_seen=V)
    turn_id: Optional[str] = jf("turn_id", STR, first_seen=V)
    item: Optional[Mapping[str, Any]] = jf("item", OBJ, first_seen=V)


@dataclass(frozen=True, kw_only=True)
class EvTurnAborted:

    type: Optional[str] = jf("type", STR, required=True)
    reason: Optional[str] = jf("reason", STR)
    turn_id: Optional[str] = jf("turn_id", STR)


@dataclass(frozen=True, kw_only=True)
class EvText:

    type: Optional[str] = jf("type", STR, required=True)
    text: Optional[str] = jf("text", STR)


@dataclass(frozen=True, kw_only=True)
class EvError:

    type: Optional[str] = jf("type", STR, required=True)
    message: Optional[str] = jf("message", STR)


RESPONSE_ITEM_TYPES: Dict[str, type] = {
    "message": RiMessage,
    "reasoning": RiReasoning,
    "function_call": RiFunctionCall,
    "function_call_output": RiFunctionCallOutput,
    "custom_tool_call": RiCustomToolCall,
    "custom_tool_call_output": RiCustomToolCallOutput,
    "web_search_call": RiWebSearchCall,
    "local_shell_call": RiLocalShellCall,
    "ghost_snapshot": RiGhostSnapshot,
}

EVENT_MSG_TYPES: Dict[str, type] = {
    "token_count": EvTokenCount,
    "agent_message": EvAgentMessage,
    "user_message": EvUserMessage,
    "task_started": EvTaskStarted,
    "task_complete": EvTaskComplete,
    "context_compacted": EvContextCompacted,
    "item_completed": EvItemCompleted,
    "turn_aborted": EvTurnAborted,
    "agent_reasoning": EvText,
    "agent_reasoning_raw_content": EvText,
    "error": EvError,
}

MEASURED_PAYLOAD_TYPES: frozenset = frozenset({
    "message", "reasoning", "function_call", "function_call_output", "custom_tool_call",
    "custom_tool_call_output", "web_search_call", "token_count", "agent_message",
    "user_message", "task_started", "task_complete", "context_compacted", "item_completed",
})


@dataclass(frozen=True)
class CodexLine:

    type: str
    timestamp: Optional[str]
    payload_type: Optional[str]
    payload: Any
    legacy: bool = False
