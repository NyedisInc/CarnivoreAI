
from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional

from src.config.byoai_extra_body import EXTRA_BODY_OPTION, ExtraBodyError, parse_extra_body
from src.core.byoai import transport
from src.core.byoai.contracts import (
    CAP_CHAT, CAP_EMBED, EXTRA_CHAT_STREAM, EXTRA_LIST_MODELS, EXTRA_TEST, PROTO_OPENAI_CHAT,
    ByoaiError, ChatDelta, ChatRequest, ChatResult, Connection, EmbedResult, ModelInfo,
    Target, TestResult, ToolCall, Usage,
)
from src.core.byoai.wire import _shared

PROTOCOL = PROTO_OPENAI_CHAT
CAPABILITIES: frozenset = frozenset({CAP_CHAT, CAP_EMBED})
EXTRAS: frozenset = frozenset({EXTRA_LIST_MODELS, EXTRA_TEST, EXTRA_CHAT_STREAM})


def _messages(request: ChatRequest) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    system = _shared.system_text(request)
    if system:
        out.append({"role": "system", "content": system})
    for m in _shared.conversation(request):
        if m.role == "tool":
            out.append({"role": "tool", "tool_call_id": m.tool_call_id or "", "content": m.content})
        elif m.role == "assistant" and m.tool_calls:
            out.append({"role": "assistant", "content": m.content or None, "tool_calls": [
                {"id": c.id, "type": "function",
                 "function": {"name": c.name, "arguments": _shared.dump_arguments(c.arguments)}}
                for c in m.tool_calls]})
        else:
            out.append({"role": m.role, "content": m.content})
    return out


def connection_extra(connection: Connection) -> Dict[str, Any]:
    try:
        return parse_extra_body(connection.options.get(EXTRA_BODY_OPTION))
    except ExtraBodyError as exc:
        raise ByoaiError(str(exc)) from None


def build_body(model: str, request: ChatRequest, *, stream: bool = False,
               connection_fields: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"model": model, "messages": _messages(request)}
    if request.max_tokens is not None:
        body["max_tokens"] = request.max_tokens
    if request.temperature is not None:
        body["temperature"] = request.temperature
    if request.tools:
        body["tools"] = [{"type": "function", "function": {
            "name": t.name, "description": t.description,
            "parameters": dict(t.parameters) or {"type": "object", "properties": {}}}}
            for t in request.tools]
    if request.json_schema is not None:
        body["response_format"] = {"type": "json_schema", "json_schema": {
            "name": "answer", "schema": dict(request.json_schema), "strict": True}}
    if stream:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
    body.update(connection_fields or {})
    body.update(request.extra)
    return body


def _usage(raw: Any) -> Usage:
    if not isinstance(raw, dict):
        return Usage()
    return Usage(_shared.whole(raw.get("prompt_tokens")), _shared.whole(raw.get("completion_tokens")),
                 _shared.number(raw.get("cost")))


def _calls(raw: Any) -> tuple:
    return tuple(ToolCall(str(c.get("id") or ""), str((c.get("function") or {}).get("name") or ""),
                          _shared.parse_arguments((c.get("function") or {}).get("arguments")))
                 for c in (raw or []))


async def chat(target: Target, key: Optional[str], request: ChatRequest) -> ChatResult:
    body = build_body(_shared.require_model(target), request, connection_fields=connection_extra(target.connection))
    data = (await transport.request(target.connection, key, "POST", "/chat/completions", json=body, timeout=request.timeout_s)).json()
    choices = data.get("choices") or []
    if not choices:
        raise ByoaiError("the provider answered with no choices")
    message = choices[0].get("message") or {}
    return ChatResult(text=message.get("content") or "", tool_calls=_calls(message.get("tool_calls")),
                      usage=_usage(data.get("usage")), finish_reason=choices[0].get("finish_reason"),
                      raw=data)


async def chat_stream(target: Target, key: Optional[str], request: ChatRequest) -> AsyncIterator[ChatDelta]:
    body = build_body(_shared.require_model(target), request, stream=True,
                      connection_fields=connection_extra(target.connection))
    pending: Dict[int, Dict[str, Any]] = {}
    usage: Optional[Usage] = None
    async with transport.stream(target.connection, key, "POST", "/chat/completions", json=body, timeout=request.timeout_s) as response:
        async for _event, chunk in _shared.sse_events(response):
            if isinstance(chunk.get("error"), dict):
                raise ByoaiError("the stream reported an error")
            if chunk.get("usage"):
                usage = _usage(chunk["usage"])
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    yield ChatDelta(text=delta["content"])
                for part in delta.get("tool_calls") or []:
                    slot = pending.setdefault(int(part.get("index") or 0), {"id": "", "name": "", "args": ""})
                    slot["id"] = part.get("id") or slot["id"]
                    fn = part.get("function") or {}
                    slot["name"] = fn.get("name") or slot["name"]
                    slot["args"] += fn.get("arguments") or ""
    calls = tuple(ToolCall(s["id"], s["name"], _shared.parse_arguments(s["args"]))
                  for _i, s in sorted(pending.items()))
    yield ChatDelta(tool_calls=calls, usage=usage, done=True)


async def embed(target: Target, key: Optional[str], inputs: List[str]) -> EmbedResult:
    body = {"model": _shared.require_model(target), "input": inputs}
    data = (await transport.request(target.connection, key, "POST", "/embeddings", json=body)).json()
    rows = sorted(data.get("data") or [], key=lambda r: r.get("index", 0))
    if len(rows) != len(inputs):
        raise ByoaiError("the provider returned the wrong number of vectors")
    usage = data.get("usage") or {}
    return EmbedResult(vectors=tuple(tuple(float(x) for x in r.get("embedding") or ()) for r in rows),
                       usage=Usage(_shared.whole(usage.get("prompt_tokens")), None, _shared.number(usage.get("cost"))),
                       raw=data)


async def list_models(connection: Connection, key: Optional[str]) -> List[ModelInfo]:
    data = (await transport.request(connection, key, "GET", "/models")).json()
    return [_shared.infer_model(str(e["id"]), e) for e in data.get("data") or [] if isinstance(e, dict) and e.get("id")]


async def test(target: Target, key: Optional[str], capability: str) -> TestResult:
    return await _shared.smoke_test(target, key, capability, chat, embed)
