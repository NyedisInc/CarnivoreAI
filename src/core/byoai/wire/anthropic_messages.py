
from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional

from src.core.byoai import transport
from src.core.byoai.contracts import (
    CAP_CHAT, EXTRA_CHAT_STREAM, EXTRA_LIST_MODELS, EXTRA_TEST, PROTO_ANTHROPIC_MESSAGES,
    ByoaiError, ChatDelta, ChatRequest, ChatResult, Connection, ModelInfo, Target, TestResult,
    ToolCall, Usage,
)
from src.core.byoai.wire import _shared

PROTOCOL = PROTO_ANTHROPIC_MESSAGES
CAPABILITIES: frozenset = frozenset({CAP_CHAT})
EXTRAS: frozenset = frozenset({EXTRA_LIST_MODELS, EXTRA_TEST, EXTRA_CHAT_STREAM})

DEFAULT_MAX_TOKENS = 4096

VERSION_HEADER = {"anthropic-version": transport.ANTHROPIC_VERSION}


def _path(connection: Connection, tail: str) -> str:
    return f"/{tail}" if connection.base_url.rstrip("/").endswith("/v1") else f"/v1/{tail}"


def _messages(request: ChatRequest) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for m in _shared.conversation(request):
        if m.role == "tool":
            block = {"type": "tool_result", "tool_use_id": m.tool_call_id or "", "content": m.content}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) \
                    and out[-1]["content"][-1].get("type") == "tool_result":
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        elif m.role == "assistant" and m.tool_calls:
            blocks: List[Dict[str, Any]] = [{"type": "text", "text": m.content}] if m.content else []
            blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": dict(c.arguments)}
                       for c in m.tool_calls]
            out.append({"role": "assistant", "content": blocks})
        else:
            out.append({"role": m.role, "content": m.content})
    return out


def build_body(model: str, request: ChatRequest, *, stream: bool = False) -> Dict[str, Any]:
    body: Dict[str, Any] = {"model": model, "max_tokens": request.max_tokens or DEFAULT_MAX_TOKENS,
                            "messages": _messages(request)}
    system = _shared.system_text(request)
    if system:
        body["system"] = system
    if request.temperature is not None:
        body["temperature"] = request.temperature
    if request.tools:
        body["tools"] = [{"name": t.name, "description": t.description,
                          "input_schema": dict(t.parameters) or {"type": "object", "properties": {}}}
                         for t in request.tools]
    if request.json_schema is not None:
        body["output_config"] = {"format": {"type": "json_schema", "schema": dict(request.json_schema)}}
    if stream:
        body["stream"] = True
    body.update(request.extra)
    return body


def _usage(raw: Any, base: Optional[Usage] = None) -> Usage:
    raw = raw if isinstance(raw, dict) else {}
    base = base or Usage()
    return Usage(_shared.whole(raw.get("input_tokens")) if raw.get("input_tokens") is not None else base.input_tokens,
                 _shared.whole(raw.get("output_tokens")) if raw.get("output_tokens") is not None else base.output_tokens,
                 base.cost_usd)


async def chat(target: Target, key: Optional[str], request: ChatRequest) -> ChatResult:
    body = build_body(_shared.require_model(target), request)
    data = (await transport.request_json(target.connection, key, "POST", _path(target.connection, "messages"),
                                    json=body, headers=VERSION_HEADER, timeout=request.timeout_s))
    if data.get("type") == "error":
        raise ByoaiError("the provider reported an error")
    text = "".join(b.get("text") or "" for b in data.get("content") or [] if b.get("type") == "text")
    calls = tuple(ToolCall(str(b.get("id") or ""), str(b.get("name") or ""), _shared.parse_arguments(b.get("input")))
                  for b in data.get("content") or [] if b.get("type") == "tool_use")
    return ChatResult(text=text, tool_calls=calls, usage=_usage(data.get("usage")),
                      finish_reason=data.get("stop_reason"), raw=data)


async def chat_stream(target: Target, key: Optional[str], request: ChatRequest) -> AsyncIterator[ChatDelta]:
    body = build_body(_shared.require_model(target), request, stream=True)
    blocks: Dict[int, Dict[str, Any]] = {}
    usage = Usage()
    async with transport.stream(target.connection, key, "POST", _path(target.connection, "messages"),
                                json=body, headers=VERSION_HEADER, timeout=request.timeout_s) as response:
        async for event, data in _shared.sse_events(response):
            kind = str(data.get("type") or event)
            if kind == "message_start":
                usage = _usage((data.get("message") or {}).get("usage"), usage)
            elif kind == "content_block_start":
                block = data.get("content_block") or {}
                if block.get("type") == "tool_use":
                    blocks[int(data.get("index") or 0)] = {"id": block.get("id") or "",
                                                           "name": block.get("name") or "", "args": ""}
            elif kind == "content_block_delta":
                delta = data.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    yield ChatDelta(text=delta["text"])
                elif delta.get("type") == "input_json_delta":
                    slot = blocks.get(int(data.get("index") or 0))
                    if slot is not None:
                        slot["args"] += delta.get("partial_json") or ""
            elif kind == "message_delta":
                usage = _usage(data.get("usage"), usage)
            elif kind == "error":
                raise ByoaiError("the stream reported an error")
    calls = tuple(ToolCall(b["id"], b["name"], _shared.parse_arguments(b["args"])) for _i, b in sorted(blocks.items()))
    yield ChatDelta(tool_calls=calls, usage=usage, done=True)


async def list_models(connection: Connection, key: Optional[str]) -> List[ModelInfo]:
    data = (await transport.request_json(connection, key, "GET", _path(connection, "models"),
                                    params={"limit": 1000}, headers=VERSION_HEADER))
    return [_shared.infer_model(str(e["id"]), e) for e in data.get("data") or [] if isinstance(e, dict) and e.get("id")]


async def test(target: Target, key: Optional[str], capability: str) -> TestResult:
    return await _shared.smoke_test(target, key, capability, chat, None)
