
from __future__ import annotations

from typing import Any, Dict, List

from src.core.mcp.common import ToolError

PROFILE_TOP = 15
PROFILE_FRAMES = 8
MODELS_CAP = 25
SESSIONS_LEAN_ROWS = 50
PROJECT_DESCRIPTION_CHARS = 120

_ROSTER_KEYS = ("id", "slug", "display_name", "rank", "state", "parent_id", "job", "project_id", "company_id", "specialty",
                "session_id", "tmux_session", "activity", "alert", "alert_reason", "host_label", "question_waiting")
_MESSAGE_KEYS = ("id", "thread", "source", "sender_id", "sender_name", "receiver_id", "receiver_name", "text", "in_reply_to",
                 "expect_reply", "status", "reason", "created_at", "task_item")
_WATCH_KEYS = ("id", "target_id", "once", "status", "notifications")


def detail_flag(args: dict) -> bool:
    value = args.get("detail", False)
    if not isinstance(value, bool):
        raise ToolError("detail must be true or false")
    return value


def _pick(row: Dict[str, Any], keys: tuple) -> Dict[str, Any]:
    return {k: row[k] for k in keys if k in row}


def swarm_roster(roster: Dict[str, Any]) -> Dict[str, Any]:
    return {"agents": [_pick(a, _ROSTER_KEYS) for a in roster.get("agents", [])], "limits": roster.get("limits")}


def crosstalk_inbox(inbox: Dict[str, Any]) -> Dict[str, Any]:
    return {"messages": [_pick(m, _MESSAGE_KEYS) for m in inbox.get("messages", [])],
            "watches": [_pick(w, _WATCH_KEYS) for w in inbox.get("watches", [])]}


def project_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for row in rows:
        text = row.get("description") or ""
        if not text:
            out.append(dict(row))
            continue
        short = text if len(text) <= PROJECT_DESCRIPTION_CHARS else text[:PROJECT_DESCRIPTION_CHARS - 3].rstrip() + "..."
        out.append({**row, "description": short})
    return out


def profile(result: Dict[str, Any], top: int) -> Dict[str, Any]:
    out = dict(result)
    stacks = []
    for stack in result.get("stacks", [])[:top]:
        frames = stack.get("frames_leaf_first", [])
        stacks.append({**stack, "frames_leaf_first": frames[:PROFILE_FRAMES], "frames_total": len(frames)})
    out["stacks"] = stacks
    for key in ("threads", "functions_inclusive", "functions_self"):
        out[key] = result.get(key, [])[:top]
    calls = result.get("calls")
    if isinstance(calls, dict):
        out["calls"] = {event: (rows[:top] if event != "totals" else rows) for event, rows in calls.items()}
    return out


def models(answer: Dict[str, Any]) -> Dict[str, Any]:
    rows = answer.get("models")
    if not isinstance(rows, list) or len(rows) <= MODELS_CAP:
        return answer
    return {**answer, "models": rows[:MODELS_CAP], "models_total": len(rows),
            "models_note": f"first {MODELS_CAP} of {len(rows)}; call again with detail true for all"}
