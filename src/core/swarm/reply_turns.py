
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

END_STOPS = frozenset({"end_turn", "stop_sequence", "max_tokens", "refusal"})
INTERRUPT = "[Request interrupted by user"
WINDOWS = (2 * 1024 * 1024, 16 * 1024 * 1024, 64 * 1024 * 1024)

Matcher = Callable[[str, Optional[datetime]], bool]


@dataclass(frozen=True)
class Turn:

    key: str
    complete: bool
    text: Optional[str] = None
    so_far: Optional[str] = None


def read_tail(path: str, limit: int) -> List[Dict[str, Any]]:
    with open(path, "rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        stream.seek(max(0, size - limit))
        if stream.tell():
            stream.readline()
        out: List[Dict[str, Any]] = []
        for line in stream:
            try:
                row = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(row, dict):
                out.append(row)
        return out


def _stamp(record: Dict[str, Any]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(record["timestamp"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None


def _blocks(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def typed_text(record: Dict[str, Any]) -> Optional[str]:
    if record.get("type") != "user" or record.get("isSidechain"):
        return None
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    blocks = _blocks(record)
    if not blocks or any(b.get("type") == "tool_result" for b in blocks):
        return None
    return "\n".join(str(b.get("text") or "") for b in blocks if b.get("type") == "text") or None


def prompt_text(record: Dict[str, Any]) -> Optional[str]:
    attachment = record.get("attachment")
    if record.get("type") == "attachment" and isinstance(attachment, dict) and attachment.get("type") == "queued_command":
        prompt = attachment.get("prompt")
        if isinstance(prompt, list):
            prompt = "\n".join(str(b.get("text") or "") for b in prompt if isinstance(b, dict) and b.get("type") == "text")
        return prompt if isinstance(prompt, str) and prompt else None
    return typed_text(record)


def _interrupted(record: Dict[str, Any]) -> bool:
    if record.get("type") != "user" or record.get("isSidechain"):
        return False
    content = (record.get("message") or {}).get("content") if isinstance(record.get("message"), dict) else None
    if isinstance(content, str):
        return content.startswith(INTERRUPT)
    return any(b.get("type") == "text" and str(b.get("text") or "").startswith(INTERRUPT) for b in _blocks(record))


def claude_turn(records: List[Dict[str, Any]], matches: Matcher) -> Optional[Turn]:
    start = next((i for i in range(len(records) - 1, -1, -1)
                  if (text := prompt_text(records[i])) is not None and matches(text, _stamp(records[i]))), None)
    if start is None:
        return None
    key = str(records[start].get("promptId") or records[start].get("uuid") or f"line:{start}")
    final_id = None
    for record in records[start + 1:]:
        if _interrupted(record):
            return Turn(key, True)
        message = record.get("message")
        if (record.get("type") == "assistant" and not record.get("isSidechain") and isinstance(message, dict)
                and message.get("stop_reason") in END_STOPS):
            final_id = message.get("id")
            break
    if final_id is None:
        written = [str(b.get("text") or "") for r in records[start + 1:]
                   if r.get("type") == "assistant" and not r.get("isSidechain") for b in _blocks(r) if b.get("type") == "text"]
        return Turn(key, False, None, _joined(written))
    texts = [str(b.get("text") or "") for r in records[start + 1:]
             if r.get("type") == "assistant" and not r.get("isSidechain") and (r.get("message") or {}).get("id") == final_id
             for b in _blocks(r) if b.get("type") == "text"]
    return Turn(f"answer:{final_id}" if final_id else key, True, "\n\n".join(t for t in texts if t.strip()).strip() or None)


def codex_turn(records: List[Dict[str, Any]], matches: Matcher) -> Optional[Turn]:
    def event(record: Dict[str, Any]) -> Dict[str, Any]:
        payload = record.get("payload")
        return payload if record.get("type") == "event_msg" and isinstance(payload, dict) else {}

    start = next((i for i in range(len(records) - 1, -1, -1)
                  if event(records[i]).get("type") == "user_message"
                  and matches(str(event(records[i]).get("message") or ""), _stamp(records[i]))), None)
    if start is None:
        return None
    written: List[str] = []
    for i, record in enumerate(records[start + 1:], start + 1):
        payload = event(record)
        if payload.get("type") in ("task_complete", "turn_aborted"):
            key = f"codex:{payload.get('turn_id') or f'line:{i}'}"
            text = payload.get("last_agent_message") if payload.get("type") == "task_complete" else None
            return Turn(key, True, text.strip() if isinstance(text, str) and text.strip() else None)
        if payload.get("type") == "agent_message" and isinstance(payload.get("message"), str):
            written.append(payload["message"])
    return Turn(f"codex:line:{start}", False, None, _joined(written))


def _joined(texts: List[str]) -> Optional[str]:
    return "\n\n".join(t.strip() for t in texts if t.strip()) or None


def find_turn(path: str, family: str, matches: Matcher) -> Optional[Turn]:
    parse = codex_turn if family == "codex" else claude_turn
    size = os.path.getsize(path)
    for limit in WINDOWS:
        turn = parse(read_tail(path, limit), matches)
        if turn is not None or limit >= size:
            return turn
    return None
