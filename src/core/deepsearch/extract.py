
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from src.core.stream_redactor import redact_whole
from src.core.transcript_source.recent_messages import clean
from src.core.deepsearch import constants as K

Extracted = Optional[Tuple[str, str]]

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _apply(action: Any, text: str) -> str:
    if action == K.KEEP:
        return text
    if isinstance(action, int) and not isinstance(action, bool):
        return redact_whole(text)[:action]
    return ""


def _tool_call_text(name: str, args: Any, rules: Dict[str, Any]) -> str:
    action = rules["tools"].get(name, rules["blocks"]["tool_use"])
    if action == K.DROP:
        return ""
    parts = [name]
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    if isinstance(args, dict):
        for key in rules["tool_use_fields"]:
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(" ".join(value.split()))
            elif isinstance(value, list) and all(isinstance(v, str) for v in value):
                parts.append(" ".join(value))
    return _apply(action, " ".join(parts))


def _tool_result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and isinstance(b.get("text"), str))
    return ""


def _finish(kind: str, parts: List[str], rules: Dict[str, Any]) -> Extracted:
    joined = "\n".join(p for p in parts if p and p.strip())
    if not joined:
        return None
    joined = redact_whole(joined)
    limit = rules["max_message_chars"]
    text = clean(joined, limit) if rules["strip_harness_wrappers"] else _CONTROL.sub("", joined).strip()[:limit]
    return (kind, text) if text else None


def _claude(rec: Dict[str, Any], rules: Dict[str, Any]) -> Extracted:
    rtype = rec.get("type")
    if rtype not in ("user", "assistant") or rec.get("isMeta"):
        return None
    if rec.get("isSidechain") and rules["sidechain"] == K.DROP:
        return None
    message = rec.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if rtype == "user" and rec.get("isCompactSummary"):
        text = content if isinstance(content, str) else _tool_result_text(content)
        return _finish(K.KIND_SUMMARY, [_apply(rules["compact_summary"], text)], rules)
    if isinstance(content, str):
        return _finish(rtype, [_apply(rules["blocks"]["text"], content)], rules)
    if not isinstance(content, list):
        return None
    parts: List[str] = []
    kinds = set()
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text" and isinstance(block.get("text"), str):
            piece, kind = _apply(rules["blocks"]["text"], block["text"]), rtype
        elif btype == "thinking" and isinstance(block.get("thinking"), str):
            piece, kind = _apply(rules["blocks"]["thinking"], block["thinking"]), K.KIND_THINKING
        elif btype == "tool_use" and isinstance(block.get("name"), str):
            piece, kind = _tool_call_text(block["name"], block.get("input"), rules), K.KIND_TOOL
        elif btype == "tool_result":
            piece, kind = _apply(rules["blocks"]["tool_result"], _tool_result_text(block.get("content"))), K.KIND_TOOL
        else:
            continue
        if piece:
            parts.append(piece)
            kinds.add(kind)
    kind = rtype if rtype in kinds else (K.KIND_TOOL if K.KIND_TOOL in kinds else K.KIND_THINKING)
    return _finish(kind, parts, rules)


def _codex(rec: Dict[str, Any], rules: Dict[str, Any]) -> Extracted:
    payload = rec.get("payload")
    if not isinstance(payload, dict):
        return None
    ptype = payload.get("type")
    if rec.get("type") == "event_msg" and ptype == "user_message" and isinstance(payload.get("message"), str):
        return _finish(K.KIND_USER, [_apply(rules["blocks"]["text"], payload["message"])], rules)
    if rec.get("type") != "response_item":
        return None
    if ptype == "message" and payload.get("role") == "assistant":
        texts = [b["text"] for b in payload.get("content") or [] if isinstance(b, dict) and isinstance(b.get("text"), str)]
        return _finish(K.KIND_ASSISTANT, [_apply(rules["blocks"]["text"], t) for t in texts], rules)
    if ptype == "function_call" and isinstance(payload.get("name"), str):
        return _finish(K.KIND_TOOL, [_tool_call_text(payload["name"], payload.get("arguments"), rules)], rules)
    if ptype == "function_call_output":
        output = payload.get("output")
        text = output if isinstance(output, str) else json.dumps(output) if output is not None else ""
        return _finish(K.KIND_TOOL, [_apply(rules["blocks"]["tool_result"], text)], rules)
    if ptype == "reasoning":
        summary = payload.get("summary") or []
        texts = [b.get("text", "") for b in summary if isinstance(b, dict)]
        return _finish(K.KIND_THINKING, [_apply(rules["blocks"]["thinking"], t) for t in texts], rules)
    return None


def extract(line: bytes, rules: Dict[str, Any], family: str) -> Extracted:
    try:
        rec = json.loads(line)
    except ValueError:
        return None
    if not isinstance(rec, dict):
        return None
    return _codex(rec, rules) if family == "codex" else _claude(rec, rules)


def record_time(line: bytes) -> Optional[str]:
    try:
        rec = json.loads(line)
    except ValueError:
        return None
    stamp = rec.get("timestamp") if isinstance(rec, dict) else None
    return stamp if isinstance(stamp, str) and stamp else None


def record_identity(line: bytes) -> Tuple[Optional[str], Optional[str]]:
    try:
        rec = json.loads(line)
    except ValueError:
        return None, None
    if not isinstance(rec, dict):
        return None, None
    stamp, uuid = rec.get("timestamp"), rec.get("uuid")
    return (stamp if isinstance(stamp, str) and stamp else None, uuid if isinstance(uuid, str) and uuid else None)
