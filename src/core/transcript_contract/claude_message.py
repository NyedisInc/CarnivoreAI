
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Tuple, Union

from src.core.transcript_contract.claude_blocks import Block, parse_blocks
from src.core.transcript_contract.fields import (
    ARR,
    INT,
    NULL,
    OBJ,
    STR,
    Report,
    bind,
    jf,
)


@dataclass(frozen=True, kw_only=True)
class Usage:

    input_tokens: Optional[int] = jf("input_tokens", INT, required=True, first_seen="1.0.62")
    output_tokens: Optional[int] = jf("output_tokens", INT, required=True, first_seen="1.0.62")
    cache_creation_input_tokens: Optional[int] = jf("cache_creation_input_tokens", INT,
                                                    first_seen="1.0.62")
    cache_read_input_tokens: Optional[int] = jf("cache_read_input_tokens", INT, first_seen="1.0.62")
    cache_creation: Optional[Mapping[str, Any]] = jf("cache_creation", OBJ, first_seen="1.0.80")
    server_tool_use: Optional[Mapping[str, Any]] = jf("server_tool_use", OBJ, first_seen="1.0.63")
    service_tier: Optional[str] = jf("service_tier", NULL + STR, first_seen="1.0.62")
    inference_geo: Optional[str] = jf("inference_geo", NULL + STR, first_seen="2.1.31")
    iterations: Optional[List[Any]] = jf("iterations", ARR + NULL, first_seen="2.1.38")
    speed: Optional[str] = jf("speed", NULL + STR, first_seen="2.1.41")
    output_tokens_details: Optional[Mapping[str, Any]] = jf("output_tokens_details", NULL + OBJ,
                                                            first_seen="2.1.149")
    fallback_credit: Optional[Any] = jf("fallback_credit", NULL, first_seen="2.1.285")


def _usage(value: Any, path: str, report: Report) -> Usage:
    return bind(Usage, value, path, report)


def _assistant_content(value: Any, path: str, report: Report) -> Tuple[Block, ...]:
    return parse_blocks(value, path, report, "assistant")


def _user_content(value: Any, path: str, report: Report) -> Union[str, Tuple[Block, ...]]:
    if isinstance(value, str):
        return value
    return parse_blocks(value, path, report, "user")


@dataclass(frozen=True, kw_only=True)
class AssistantMessage:

    role: Optional[str] = jf("role", STR, required=True, first_seen="1.0.62")
    model: Optional[str] = jf("model", STR, required=True, first_seen="1.0.62")
    content: Optional[Tuple[Block, ...]] = jf("content", ARR, required=True, first_seen="1.0.62",
                                              nested=_assistant_content)
    usage: Optional[Usage] = jf("usage", OBJ, required=True, first_seen="1.0.62", nested=_usage)
    id: Optional[str] = jf("id", STR, first_seen="1.0.62")
    type: Optional[str] = jf("type", STR, first_seen="1.0.62")
    stop_reason: Optional[str] = jf("stop_reason", NULL + STR, first_seen="1.0.62")
    stop_sequence: Optional[str] = jf("stop_sequence", NULL + STR, first_seen="1.0.62")
    stop_details: Optional[Mapping[str, Any]] = jf("stop_details", NULL + OBJ, first_seen="2.1.83")
    container: Optional[Any] = jf("container", NULL, first_seen="2.0.1")
    context_management: Optional[Mapping[str, Any]] = jf("context_management", NULL + OBJ,
                                                         first_seen="2.0.64")
    diagnostics: Optional[Mapping[str, Any]] = jf("diagnostics", NULL + OBJ, first_seen="2.1.119")
    input_transformations: Optional[List[Any]] = jf("input_transformations", ARR,
                                                    first_seen="2.1.263")


@dataclass(frozen=True, kw_only=True)
class UserMessage:

    role: Optional[str] = jf("role", STR, required=True, first_seen="1.0.61")
    content: Optional[Union[str, Tuple[Block, ...]]] = jf(
        "content", ARR + STR, required=True, first_seen="1.0.61", nested=_user_content)


def parse_assistant_message(value: Any, path: str, report: Report) -> AssistantMessage:
    return bind(AssistantMessage, value, path, report)


def parse_user_message(value: Any, path: str, report: Report) -> UserMessage:
    return bind(UserMessage, value, path, report)
