
from __future__ import annotations

import json
from typing import Any, Dict, Iterator, Optional


def latest_user_text(body: Dict[str, Any]) -> str:
    items = body.get("input")
    if isinstance(items, str):
        return items
    if not items or items[-1].get("role") != "user":
        return ""
    content = items[-1].get("content")
    if isinstance(content, str):
        return content
    return "\n".join(p.get("text", "") for p in content or [] if isinstance(p, dict))


def _event(data: Dict[str, Any]) -> bytes:
    return f"event: {data['type']}\ndata: {json.dumps(data)}\n\n".encode()


def stream(text: str, tool: Optional[Dict[str, Any]], call_id: str) -> Iterator[bytes]:
    base = {"id": "resp_rig", "object": "response", "model": "rig-model", "status": "in_progress", "output": []}
    yield _event({"type": "response.created", "response": base})
    if tool:
        name, namespace = tool["name"], None
        if name.startswith("mcp__") and name.count("__") >= 2:
            head, name = name.rsplit("__", 1)
            namespace = head
        item = {"type": "function_call", "id": "fc_" + call_id, "call_id": call_id, "name": name,
                "arguments": json.dumps(tool["input"]), "status": "completed"}
        if namespace:
            item["namespace"] = namespace
        yield _event({"type": "response.output_item.added", "output_index": 0, "item": dict(item, arguments="")})
        yield _event({"type": "response.function_call_arguments.delta", "output_index": 0,
                      "item_id": item["id"], "delta": item["arguments"]})
    else:
        item = {"type": "message", "id": "msg_rig", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}]}
        yield _event({"type": "response.output_item.added", "output_index": 0,
                      "item": dict(item, content=[], status="in_progress")})
        yield _event({"type": "response.output_text.delta", "output_index": 0, "content_index": 0,
                      "item_id": "msg_rig", "delta": text})
    yield _event({"type": "response.output_item.done", "output_index": 0, "item": item})
    done = dict(base, status="completed", output=[item],
                usage={"input_tokens": 10, "output_tokens": 10, "total_tokens": 20})
    yield _event({"type": "response.completed", "response": done})
