
from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional

from src.core.byoai import transport
from src.core.byoai.contracts import (
    CAP_CHAT, EXTRA_CHAT_STREAM, EXTRA_LIST_MODELS, EXTRA_TEST, PROTO_OPENAI_RESPONSES,
    ByoaiError, ChatDelta, ChatRequest, ChatResult, Connection, ModelInfo, Target, TestResult,
    ToolCall, Usage,
)
from src.core.byoai.wire import _shared

PROTOCOL = PROTO_OPENAI_RESPONSES
CAPABILITIES: frozenset = frozenset({CAP_CHAT})
EXTRAS: frozenset = frozenset({EXTRA_LIST_MODELS, EXTRA_TEST, EXTRA_CHAT_STREAM})


def _input(request: ChatRequest) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for m in _shared.conversation(request):
        if m.role == "tool":
            items.append({"type": "function_call_output", "call_id": m.tool_call_id or "", "output": m.content})
            continue
        if m.content or not m.tool_calls:
            items.append({"role": m.role, "content": m.content})
        for c in m.tool_calls:
            items.append({"type": "function_call", "call_id": c.id, "name": c.name,
                          "arguments": _shared.dump_arguments(c.arguments)})
    return items


def build_body(model: str, request: ChatRequest, *, stream: bool = False) -> Dict[str, Any]:
    body: Dict[str, Any] = {"model": model, "input": _input(request)}
    system = _shared.system_text(request)
    if system:
        body["instructions"] = system
    if request.max_tokens is not None:
        body["max_output_tokens"] = request.max_tokens
    if request.temperature is not None:
        body["temperature"] = request.temperature
    if request.tools:
        body["tools"] = [{"type": "function", "name": t.name, "description": t.description,
                          "parameters": dict(t.parameters) or {"type": "object", "properties": {}}}
                         for t in request.tools]
    if request.json_schema is not None:
        body["text"] = {"format": {"type": "json_schema", "name": "answer",
                                   "schema": dict(request.json_schema), "strict": True}}
    if stream:
        body["stream"] = True
    body.update(request.extra)
    return body


def _usage(raw: Any) -> Usage:
    if not isinstance(raw, dict):
        return Usage()
    return Usage(_shared.whole(raw.get("input_tokens")), _shared.whole(raw.get("output_tokens")),
                 _shared.number(raw.get("cost")))


def _call(item: Dict[str, Any]) -> ToolCall:
    return ToolCall(str(item.get("call_id") or item.get("id") or ""), str(item.get("name") or ""),
                    _shared.parse_arguments(item.get("arguments")))


def parse_output(data: Dict[str, Any]) -> ChatResult:
    if data.get("status") == "failed" or isinstance(data.get("error"), dict):
        raise ByoaiError("the provider reported the response failed")
    text: List[str] = []
    calls: List[ToolCall] = []
    for item in data.get("output") or []:
        if item.get("type") == "message":
            text += [p.get("text") or "" for p in item.get("content") or [] if p.get("type") == "output_text"]
        elif item.get("type") == "function_call":
            calls.append(_call(item))
    reason = (data.get("incomplete_details") or {}).get("reason") or data.get("status")
    return ChatResult(text="".join(text), tool_calls=tuple(calls), usage=_usage(data.get("usage")),
                      finish_reason=reason, raw=data)


async def chat(target: Target, key: Optional[str], request: ChatRequest) -> ChatResult:
    body = build_body(_shared.require_model(target), request)
    return parse_output((await transport.request(target.connection, key, "POST", "/responses", json=body, timeout=request.timeout_s)).json())


async def chat_stream(target: Target, key: Optional[str], request: ChatRequest) -> AsyncIterator[ChatDelta]:
    body = build_body(_shared.require_model(target), request, stream=True)
    calls: List[ToolCall] = []
    usage: Optional[Usage] = None
    async with transport.stream(target.connection, key, "POST", "/responses", json=body, timeout=request.timeout_s) as response:
        async for event, data in _shared.sse_events(response):
            kind = str(data.get("type") or event)
            if kind == "response.output_text.delta" and data.get("delta"):
                yield ChatDelta(text=str(data["delta"]))
            elif kind == "response.output_item.done" and (data.get("item") or {}).get("type") == "function_call":
                calls.append(_call(data["item"]))
            elif kind in ("response.completed", "response.incomplete"):
                usage = _usage((data.get("response") or {}).get("usage"))
            elif kind in ("response.failed", "error"):
                raise ByoaiError("the stream reported an error")
    yield ChatDelta(tool_calls=tuple(calls), usage=usage, done=True)


async def list_models(connection: Connection, key: Optional[str]) -> List[ModelInfo]:
    data = (await transport.request(connection, key, "GET", "/models")).json()
    return [_shared.infer_model(str(e["id"]), e) for e in data.get("data") or [] if isinstance(e, dict) and e.get("id")]


async def test(target: Target, key: Optional[str], capability: str) -> TestResult:
    return await _shared.smoke_test(target, key, capability, chat, None)
