
from __future__ import annotations

from typing import Any, Dict, List, Optional

_USER_CLIP = 4000
_ASSISTANT_CLIP = 2000
_COMPACT_CLIP = 6000
_TOOL_CLIP = 160
_TOOL_ARG_KEYS = ("file_path", "path", "command", "pattern", "url", "description")


def claude_user_text(record: Dict[str, Any]) -> Optional[str]:
    if record.get("isMeta") or record.get("isSidechain") or record.get("isCompactSummary"):
        return None
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(p for p in parts if p) or None
    return None


def codex_user_text(record: Dict[str, Any]) -> Optional[str]:
    payload = record.get("payload")
    if record.get("type") == "event_msg" and isinstance(payload, dict) \
            and payload.get("type") == "user_message":
        text = payload.get("message")
        return text if isinstance(text, str) else None
    return None


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + " [cut]"


def _tool_line(name: str, args: Any) -> str:
    detail = ""
    if isinstance(args, dict):
        for key in _TOOL_ARG_KEYS:
            if isinstance(args.get(key), str):
                detail = " ".join(args[key].split())
                break
    return _clip(f"[tool] {name}: {detail}" if detail else f"[tool] {name}", _TOOL_CLIP)


def entries_of(rec: Dict[str, Any]) -> List[str]:
    rtype = rec.get("type")
    payload = rec.get("payload")
    if rtype == "user":
        if rec.get("isCompactSummary"):
            message = rec.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            text = content if isinstance(content, str) else " ".join(
                b.get("text", "") for b in content or [] if isinstance(b, dict))
            return [f"[earlier summary] {_clip(text, _COMPACT_CLIP)}"] if text.strip() else []
        text = claude_user_text(rec)
        return [f"[user] {_clip(text, _USER_CLIP)}"] if text and text.strip() else []
    if rtype == "event_msg":
        text = codex_user_text(rec)
        return [f"[user] {_clip(text, _USER_CLIP)}"] if text and text.strip() else []
    if rtype == "response_item" and isinstance(payload, dict):
        if payload.get("type") == "function_call" and isinstance(payload.get("name"), str):
            return [_tool_line(payload["name"], None)]
        if payload.get("type") == "message" and payload.get("role") == "assistant":
            parts = [b.get("text", "") for b in payload.get("content") or []
                     if isinstance(b, dict) and isinstance(b.get("text"), str)]
            joined = "\n".join(p for p in parts if p)
            return [f"[assistant] {_clip(joined, _ASSISTANT_CLIP)}"] if joined.strip() else []
        return []
    message = rec.get("message")
    if rtype != "assistant" or not isinstance(message, dict) or rec.get("isSidechain"):
        return []
    out: List[str] = []
    for block in message.get("content") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str) and block["text"].strip():
            out.append(f"[assistant] {_clip(block['text'], _ASSISTANT_CLIP)}")
        elif block.get("type") == "tool_use" and isinstance(block.get("name"), str):
            out.append(_tool_line(block["name"], block.get("input")))
    return out
