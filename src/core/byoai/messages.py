
from __future__ import annotations

from typing import Any, List, Mapping, Sequence, Tuple, Union

from src.core.byoai.contracts import ChatMessage, ToolCall


def user(text: str) -> ChatMessage:
    return ChatMessage("user", text)


def assistant(text: str, tool_calls: Sequence[ToolCall] = ()) -> ChatMessage:
    return ChatMessage("assistant", text, tuple(tool_calls))


def system_turn(text: str) -> ChatMessage:
    return ChatMessage("system", text)


def tool_result(call_id: str, content: str) -> ChatMessage:
    return ChatMessage("tool", content, tool_call_id=call_id)


def as_messages(messages: Union[str, Sequence[Union[ChatMessage, Mapping[str, Any], str]]]) -> Tuple[ChatMessage, ...]:
    items = [messages] if isinstance(messages, str) else list(messages)
    out: List[ChatMessage] = []
    for m in items:
        if isinstance(m, ChatMessage):
            out.append(m)
        elif isinstance(m, str):
            out.append(user(m))
        else:
            out.append(ChatMessage(str(m.get("role", "user")), str(m.get("content", "")),
                                   tuple(ToolCall(str(c.get("id", "")), str(c.get("name", "")), c.get("arguments") or {})
                                         for c in m.get("tool_calls") or ()),
                                   m.get("tool_call_id")))
    return tuple(out)
