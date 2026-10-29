
from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List, Optional

RIG_MODEL = "rig-model"


def latest_user_text(body: Dict[str, Any]) -> str:
    for message in reversed(body.get("messages") or []):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        blocks = [b for b in content or [] if isinstance(b, dict)]
        if any(b.get("type") == "tool_result" for b in blocks):
            return ""
        return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    return ""


def _event(name: str, data: Dict[str, Any]) -> bytes:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()


def message_json(blocks: List[Dict[str, Any]], stop_reason: str) -> Dict[str, Any]:
    return {"id": "msg_rig", "type": "message", "role": "assistant", "model": RIG_MODEL, "content": blocks,
            "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10}}


def text_block(text: str) -> Dict[str, Any]:
    return {"type": "text", "text": text}


def tool_block(name: str, tool_input: Dict[str, Any], call_id: str) -> Dict[str, Any]:
    return {"type": "tool_use", "id": call_id, "name": name, "input": tool_input}


def stream(blocks: List[Dict[str, Any]], stop_reason: str) -> Iterator[bytes]:
    shell = message_json([], stop_reason)
    shell["stop_reason"] = None
    yield _event("message_start", {"type": "message_start", "message": shell})
    for i, block in enumerate(blocks):
        if block["type"] == "text":
            yield _event("content_block_start", {"type": "content_block_start", "index": i,
                                                 "content_block": text_block("")})
            yield _event("content_block_delta", {"type": "content_block_delta", "index": i,
                                                 "delta": {"type": "text_delta", "text": block["text"]}})
        else:
            start = dict(block, input={})
            yield _event("content_block_start", {"type": "content_block_start", "index": i, "content_block": start})
            yield _event("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {
                "type": "input_json_delta", "partial_json": json.dumps(block["input"])}})
        yield _event("content_block_stop", {"type": "content_block_stop", "index": i})
    yield _event("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop_reason,
                                                                       "stop_sequence": None},
                                   "usage": {"output_tokens": 10}})
    yield _event("message_stop", {"type": "message_stop"})


def blocks_for(text: str, tool: Optional[Dict[str, Any]], call_id: str) -> tuple[List[Dict[str, Any]], str]:
    if tool:
        return [tool_block(tool["name"], tool["input"], call_id)], "tool_use"
    return [text_block(text)], "end_turn"
