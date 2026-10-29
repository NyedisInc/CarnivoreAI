
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

from src.core.attention.turn_counts import content_blocks
from src.core.timers.redact import summary

TARGET_CHARS: int = 80

SNIPPET_CHARS: int = 200

_TARGET_KEYS: Dict[str, str] = {
    "Bash": "command",
    "Edit": "file_path",
    "MultiEdit": "file_path",
    "Write": "file_path",
    "Read": "file_path",
    "NotebookEdit": "notebook_path",
    "WebFetch": "url",
    "WebSearch": "query",
    "ExitPlanMode": "plan",
}

@dataclass(frozen=True)
class ToastFacts:

    last_text: Optional[str] = None
    pending_tool: Optional[str] = None
    pending_target: Optional[str] = None


def _question_text(tool_input: Dict[str, Any]) -> Optional[str]:
    questions = tool_input.get("questions")
    if isinstance(questions, list):
        for item in questions:
            if isinstance(item, dict) and isinstance(item.get("question"), str):
                return item["question"]
    question = tool_input.get("question")
    return question if isinstance(question, str) else None


def _target_of(name: str, tool_input: Any) -> Optional[str]:
    if not isinstance(tool_input, dict):
        return None
    if name == "AskUserQuestion":
        raw = _question_text(tool_input)
    else:
        key = _TARGET_KEYS.get(name)
        raw = tool_input.get(key) if key else None
    return summary(raw, SNIPPET_CHARS)


def _text_of(record: Dict[str, Any]) -> Optional[str]:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content if content.strip() else None
    texts = [
        block.get("text") for block in content_blocks(record, "text")
        if isinstance(block.get("text"), str) and block.get("text").strip()
    ]
    return "\n".join(texts) if texts else None


def extract_toast_facts(records: Sequence[Any]) -> ToastFacts:
    last_text: Optional[str] = None
    answered: set = set()
    last_call: Optional[Dict[str, Any]] = None
    for record in records or ():
        if not isinstance(record, dict) or record.get("isSidechain"):
            continue
        kind = record.get("type")
        if kind == "user":
            for block in content_blocks(record, "tool_result"):
                if isinstance(block.get("tool_use_id"), str):
                    answered.add(block["tool_use_id"])
        elif kind == "assistant":
            text = _text_of(record)
            if text:
                last_text = text
            calls = content_blocks(record, "tool_use")
            if calls:
                last_call = calls[-1]
    pending_tool: Optional[str] = None
    pending_target: Optional[str] = None
    if last_call is not None and last_call.get("id") not in answered:
        name = last_call.get("name")
        if isinstance(name, str) and name:
            pending_tool = summary(name, TARGET_CHARS)
            pending_target = _target_of(name, last_call.get("input"))
    return ToastFacts(
        last_text=summary(last_text, SNIPPET_CHARS),
        pending_tool=pending_tool,
        pending_target=pending_target,
    )
