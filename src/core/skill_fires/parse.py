
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

SOURCE_TOOL_USE = "tool_use"
SOURCE_SLASH = "slash"
SOURCE_INFERRED = "inferred"

HARNESS_CLAUDE = "claude"
HARNESS_CODEX = "codex"

CLAUDE_MARKS: Tuple[bytes, ...] = (b'"name":"Skill"', b"<command-name>/")
CODEX_MARKS: Tuple[bytes, ...] = (b"SKILL.md",)

BUILTIN_COMMANDS = frozenset({
    "add-dir", "agents", "bug", "clear", "compact", "config", "context", "cost",
    "doctor", "effort", "exit", "export", "help", "hooks", "ide", "init", "login",
    "logout", "mcp", "memory", "model", "permissions", "plan", "plugin",
    "progress", "rate-limit-options", "reload-plugins", "remote-control",
    "rename", "resume", "review", "rewind", "status", "statusline", "terminal-setup",
    "usage", "vim", "keybindings", "goal", "quit", "fast", "theme", "todos", "upgrade",
})

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SLASH_RE = re.compile(r"<command-name>/([^<\s]{1,128})</command-name>")
_CODEX_SKILL_RE = re.compile(r"/skills/((?:\.system/)?[A-Za-z0-9][A-Za-z0-9._-]{0,127})/SKILL\.md")
_CODEX_CALLS = frozenset({"function_call", "custom_tool_call", "local_shell_call"})


@dataclass(frozen=True)
class Fire:

    skill: str
    fired_at: Optional[str]
    source: str


def _valid(name: Any) -> bool:
    return isinstance(name, str) and _NAME_RE.match(name) is not None


def _texts(content: Any) -> List[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [b["text"] for b in content
                if isinstance(b, dict) and isinstance(b.get("text"), str)]
    return []


def parse_claude_line(line: bytes) -> List[Fire]:
    if not any(mark in line for mark in CLAUDE_MARKS):
        return []
    try:
        record = json.loads(line)
    except ValueError:
        return []
    if not isinstance(record, dict) or record.get("isSidechain") is True:
        return []
    stamp = record.get("timestamp") if isinstance(record.get("timestamp"), str) else None
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    out: List[Fire] = []
    if record.get("type") == "assistant" and isinstance(content, list):
        for block in content:
            if (isinstance(block, dict) and block.get("type") == "tool_use"
                    and block.get("name") == "Skill"
                    and isinstance(block.get("input"), dict)
                    and _valid(block["input"].get("skill"))):
                out.append(Fire(block["input"]["skill"], stamp, SOURCE_TOOL_USE))
    elif record.get("type") == "user":
        for text in _texts(content):
            for name in _SLASH_RE.findall(text):
                if _valid(name) and name not in BUILTIN_COMMANDS:
                    out.append(Fire(name, stamp, SOURCE_SLASH))
    return out


def parse_codex_line(line: bytes) -> List[Fire]:
    if not any(mark in line for mark in CODEX_MARKS):
        return []
    try:
        record = json.loads(line)
    except ValueError:
        return []
    if not isinstance(record, dict):
        return []
    payload = record.get("payload")
    if (record.get("type") != "response_item" or not isinstance(payload, dict)
            or payload.get("type") not in _CODEX_CALLS):
        return []
    stamp = record.get("timestamp") if isinstance(record.get("timestamp"), str) else None
    blob = json.dumps(payload.get("arguments") or payload.get("input") or payload.get("action") or "")
    seen: List[str] = []
    for name in _CODEX_SKILL_RE.findall(blob):
        if name not in seen:
            seen.append(name)
    return [Fire(name, stamp, SOURCE_INFERRED) for name in seen]


def parse_line(harness: str, line: bytes) -> List[Fire]:
    if harness == HARNESS_CLAUDE:
        return parse_claude_line(line)
    if harness == HARNESS_CODEX:
        return parse_codex_line(line)
    return []
