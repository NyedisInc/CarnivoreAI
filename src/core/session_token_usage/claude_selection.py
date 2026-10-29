
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.core.session_token_usage.model_table import MODEL_TABLE

ULTRACODE: str = "ultracode"

_MODEL_RE = re.compile(r"Set model to\s+(.+?)\s+(?:for this session|and saved)", re.S)

_EFFORT_RE = re.compile(r"Set effort level to\s+([A-Za-z][\w-]*)")

_ULTRA_ON_RE = re.compile(r"(?:^\s*|·\s*)Ultracode on\b")

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

_STDOUT_RE = re.compile(
    r"<local-command-stdout>(.*?)</local-command-stdout>", re.S
)


@dataclass(frozen=True)
class Selection:

    model: Optional[str] = None
    model_display: Optional[str] = None
    effort: Optional[str] = None
    ultra: Optional[bool] = None


def _display_index() -> Dict[str, str]:
    index: Dict[str, str] = {}
    for model_id, facts in MODEL_TABLE.items():
        name = _normalize_name(facts.display_name)
        if name and name not in index:
            index[name] = model_id
    return index


def _normalize_name(name: Optional[str]) -> Optional[str]:
    if not isinstance(name, str):
        return None
    text = re.sub(r"\s*\([^()]*\)\s*$", "", name.strip())
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text or None


def _command_text(record: Dict[str, Any]) -> Optional[str]:
    text: Optional[str] = None
    if record.get("type") == "system" and record.get("subtype") == "local_command":
        content = record.get("content")
        if isinstance(content, str):
            inner = _STDOUT_RE.search(content)
            text = inner.group(1) if inner else content
    elif record.get("type") == "user":
        message = record.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            inner = _STDOUT_RE.search(content)
            if inner:
                text = inner.group(1)
    if text is None:
        return None
    return _ANSI_RE.sub("", text)


def read_selection(record: Dict[str, Any]) -> Optional[Selection]:
    text = _command_text(record)
    if text is None:
        return None

    model_id: Optional[str] = None
    model_display: Optional[str] = None
    model_match = _MODEL_RE.search(text)
    if model_match:
        raw = model_match.group(1).strip().strip("`").strip("*").strip()
        if raw:
            model_display = raw
            model_id = _display_index().get(_normalize_name(raw) or "")

    effort: Optional[str] = None
    effort_match = _EFFORT_RE.search(text)
    if effort_match:
        effort = effort_match.group(1).strip().lower()

    ultra: Optional[bool] = None
    if _ULTRA_ON_RE.search(text) or effort == ULTRACODE:
        ultra = True
    elif effort is not None:
        ultra = False

    if (
        model_id is None
        and model_display is None
        and effort is None
        and ultra is None
    ):
        return None
    return Selection(
        model=model_id, model_display=model_display, effort=effort, ultra=ultra
    )


_ULTRA_MARKERS: Dict[str, bool] = {
    "ultra_effort_enter": True,
    "ultra_effort_exit": False,
}


def read_ultra_marker(record: Dict[str, Any]) -> Optional[bool]:
    if record.get("type") != "attachment":
        return None
    attachment = record.get("attachment")
    if not isinstance(attachment, dict):
        return None
    return _ULTRA_MARKERS.get(attachment.get("type"))  # type: ignore[arg-type]
