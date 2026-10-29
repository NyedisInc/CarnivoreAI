
from __future__ import annotations

from typing import Optional


def question_toast_title(hint: Optional[str]) -> str:
    if isinstance(hint, str) and hint.startswith("question:"):
        index, _, total = hint[len("question:"):].partition("/")
        if index.isdigit() and total.isdigit():
            return f"question {index} of {total} waiting"
    return "question waiting"


def hook_event_presentation(kind: str, payload: dict) -> tuple[str, Optional[str]]:
    body: Optional[str] = None

    if kind == "Stop":
        title = "Your turn"
        transcript = payload.get("transcript") or payload.get("last_model_message")
        if isinstance(transcript, str) and transcript.strip():
            body = transcript.strip()[-200:]
        else:
            stop_reason = payload.get("stop_reason")
            if isinstance(stop_reason, str) and stop_reason.strip():
                body = f"stop_reason: {stop_reason.strip()[:180]}"

    elif kind == "PermissionRequest":
        title = "needs your permission"
        tool_name = payload.get("tool_name")
        tool_input = payload.get("tool_input")
        if isinstance(tool_name, str) and tool_name:
            detail = ""
            if isinstance(tool_input, dict):
                detail = (
                    tool_input.get("command")
                    or tool_input.get("file_path")
                    or ""
                )
            body = f"{tool_name}: {detail}".strip(": ").strip()[:200] or tool_name[:200]
        else:
            prompt = payload.get("prompt") or payload.get("message")
            if isinstance(prompt, str) and prompt.strip():
                body = prompt.strip()[:200]
        if not body:
            body = "Claude is asking for permission to act."
    elif kind == "Notification":
        title = "wants your attention"
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            body = message.strip()[:200]
    else:
        title = "Claude event"

    return title, body

