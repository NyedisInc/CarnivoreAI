
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from src.core.bookmarks.transcript_index import is_turn_prompt


@dataclass(frozen=True)
class EndedTurn:

    prompt_uuid: str
    used_tools: bool


def _opens_tool(record: Dict[str, Any]) -> bool:
    if record.get("type") != "assistant" or record.get("isSidechain"):
        return False
    content = (record.get("message") or {}).get("content")
    return isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content)


def newest_turn(records: List[Dict[str, Any]]) -> Optional[EndedTurn]:
    for i in range(len(records) - 1, -1, -1):
        record = records[i]
        if record.get("uuid") and not record.get("isSidechain") and is_turn_prompt(record):
            return EndedTurn(prompt_uuid=str(record["uuid"]), used_tools=any(_opens_tool(r) for r in records[i + 1:]))
    return None


CODEX_TOOL_ITEMS = frozenset({"function_call", "local_shell_call", "custom_tool_call"})
CODEX_TURN_ENDS = frozenset({"task_complete", "turn_aborted"})


def _payload(record: Dict[str, Any]) -> Dict[str, Any]:
    payload = record.get("payload")
    return payload if isinstance(payload, dict) else {}


def newest_codex_turn(records: List[Dict[str, Any]]) -> Optional[EndedTurn]:
    for i in range(len(records) - 1, -1, -1):
        payload = _payload(records[i])
        if records[i].get("type") != "event_msg" or payload.get("type") not in CODEX_TURN_ENDS:
            continue
        turn_id = payload.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id:
            return None
        used = False
        for record in reversed(records[:i]):
            inner = _payload(record)
            if record.get("type") == "event_msg" and inner.get("type") == "user_message":
                break
            if record.get("type") == "response_item" and inner.get("type") in CODEX_TOOL_ITEMS:
                used = True
        return EndedTurn(prompt_uuid=turn_id, used_tools=used)
    return None


def codex_turn_number(lines: Iterable[str], turn_id: str) -> Optional[int]:
    import json

    seen: List[str] = []
    for line in lines:
        if '"turn_id"' not in line:
            continue
        try:
            found = _payload(json.loads(line)).get("turn_id")
        except ValueError:
            continue
        if isinstance(found, str) and found and found not in seen:
            seen.append(found)
            if found == turn_id:
                return len(seen)
    return None
