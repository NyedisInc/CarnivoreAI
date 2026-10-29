
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.cplugs.sdk.transcript_files import claude_user_text, codex_user_text

PROMPT_CHARS = 500
_TS = re.compile(rb'"timestamp"\s*:\s*"([^"]+)"')
_SCAN_LINES = 8
_CLAUDE_USER = b'"user"'
_CODEX_USER = b'user_message'
_COMPACT = b"compact_boundary"


def _clip(text: str) -> str:
    return " ".join(text.split())[:PROMPT_CHARS]


def _edge_ts(lines: List[bytes]) -> Optional[str]:
    for line in lines:
        match = _TS.search(line)
        if match:
            return match.group(1).decode("utf-8", "replace")
    return None


def chunk_digest(raw: bytes) -> Dict[str, Any]:
    lines = raw.split(b"\n")
    if lines and not lines[-1]:
        lines.pop()
    out: Dict[str, Any] = {"n": len(lines), "t": 0, "c": 0, "a": _edge_ts(lines[:_SCAN_LINES]),
                           "z": _edge_ts(lines[::-1][:_SCAN_LINES]), "f": None, "l": None}
    for line in lines:
        if _COMPACT in line:
            out["c"] += 1
        if (_CLAUDE_USER in line and b"tool_result" not in line) or _CODEX_USER in line:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            text = claude_user_text(rec) if rec.get("type") == "user" else codex_user_text(rec) if rec.get("type") == "event_msg" else None
            if text and text.strip():
                out["t"] += 1
                out["f"] = out["f"] if out["f"] is not None else _clip(text)
                out["l"] = _clip(text)
    return out


def _when(value: Optional[str]) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def merge(chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
    stamps = [t for t in [_when(c.get(k)) for c in chunks for k in ("a", "z")] if t is not None]
    first, last = (min(stamps), max(stamps)) if stamps else (None, None)
    prompts = [c["f"] for c in chunks if c.get("f") is not None]
    ends = [c["l"] for c in chunks if c.get("l") is not None]
    return {
        "turns": sum(c.get("t", 0) for c in chunks), "records": sum(c.get("n", 0) for c in chunks),
        "compactions": sum(c.get("c", 0) for c in chunks), "started_at": first.isoformat() if first else None,
        "ended_at": last.isoformat() if last else None,
        "duration_seconds": int((last - first).total_seconds()) if first and last else None,
        "first_prompt": prompts[0] if prompts else None, "last_prompt": ends[-1] if ends else None,
        "files_most_edited": [], "tools_used": [], "models": [],
    }
