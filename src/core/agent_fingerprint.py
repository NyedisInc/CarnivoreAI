from __future__ import annotations

import re
from typing import Optional, Pattern, Union

import structlog

AGENT_FINGERPRINTS: dict[str, list[Union[str, Pattern[str]]]] = {
    "openclaw": [
        "🦞 OpenClaw",
        re.compile(r"^\s*openclaw tui - ws://[\d.]+:\d+ - agent \S+ - session \S+", re.M),
        "I'm not magic-I'm just extremely persistent with retries",
    ],
    "hermes": [
        re.compile(r"Hermes Agent v[\d.]+"),
        "Welcome to Hermes Agent! Type your message or /help",
        re.compile(r"⚕\s+\S+\s+│\s+ctx\s+\S+\s+│\s+\[[░▒▓█\s]*\]"),
    ],
    "codex": [
        ">_ OpenAI Codex (v",
        re.compile(r"^\s*gpt-[\d.]+\s+(default\s+)?fast\s+·\s+~", re.M),
        "/model to change",
    ],
    "claude": [
        "Claude Code'll be able to read, edit, and execute files",
        re.compile(r"^\s*❯\s*1\.\s*Yes, I trust this folder", re.M),
        "Security guide",
        re.compile(r"^\s*╭[─\s]*Claude Code(?:\s+v[\d.]+)?\s*[─╮]", re.M),
        re.compile(r"▐▛███▜▌\s+Claude Code(?:\s+v[\d.]+)?"),
        "⏵⏵ bypass permissions on",
        "⏸ manual mode on",
        "Showing detailed transcript · ctrl+o to toggle",
        re.compile(r"claude\.com/cai/oauth/authorize"),
    ],
}


logger = structlog.get_logger()


def _matching_families(tail: str) -> set[str]:
    hits: set[str] = set()
    for agent_type, patterns in AGENT_FINGERPRINTS.items():
        for pattern in patterns:
            if isinstance(pattern, str):
                matched = pattern in tail
            else:
                matched = pattern.search(tail) is not None
            if matched:
                hits.add(agent_type)
                break
    return hits


def _resolve(tail: str) -> Optional[str]:
    hits = _matching_families(tail)
    if len(hits) == 1:
        return next(iter(hits))
    if len(hits) > 1:
        logger.warning(
            "agent_fingerprint_ambiguous_match",
            families=sorted(hits),
        )
    return None


def detect_agent_type(scrollback: Optional[str]) -> Optional[str]:
    if not scrollback:
        return None
    lines = scrollback.splitlines()
    tail = "\n".join(lines[-50:])
    hit = _resolve(tail)
    if hit is not None:
        return hit
    if len(lines) <= 50:
        return None
    tail2k = "\n".join(lines[-2000:])
    return _resolve(tail2k)
