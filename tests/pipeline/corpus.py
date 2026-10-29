
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

T0: float = datetime(2026, 9, 1, 12, 30, 0, tzinfo=timezone.utc).timestamp()

PROJECT_CWD = "/Users/x/proj"
CLAUDE_FOLDER = "-Users-x-proj"
MAIN = "11111111-aaaa-bbbb-cccc-000000000001"
FORKED = "11111111-aaaa-bbbb-cccc-000000000002"
CODEX = "rollout-2026-09-01T12-00-00-33333333-aaaa-bbbb-cccc-000000000003"
MODEL = "claude-sonnet-4-5"


def stamp(minute: int, second: int = 0) -> str:
    return f"2026-09-01T12:{minute:02d}:{second:02d}Z"


def jl(*records: Dict[str, Any]) -> bytes:
    return b"".join((json.dumps(r, sort_keys=True) + "\n").encode() for r in records)


def user(i: int, session: str, minute: int, **extra: Any) -> Dict[str, Any]:
    return {"type": "user", "uuid": f"u-{session[-1]}-{i}", "sessionId": session, "cwd": PROJECT_CWD,
            "timestamp": stamp(minute), "message": {"role": "user", "content": f"prompt {i}"}, **extra}


def assistant(i: int, session: str, minute: int, out_tokens: int, tool: Optional[str] = "Edit",
              **extra: Any) -> Dict[str, Any]:
    content: List[Dict[str, Any]] = [{"type": "text", "text": "ok"}]
    if tool:
        content.append({"type": "tool_use", "id": f"tu-{session[-1]}-{i}", "name": tool, "input": {}})
    return {"type": "assistant", "uuid": f"a-{session[-1]}-{i}", "sessionId": session, "cwd": PROJECT_CWD,
            "timestamp": stamp(minute, 20),
            "message": {"id": f"msg-{session[-1]}-{i}", "model": MODEL, "stop_reason": "end_turn",
                        "content": content, "usage": {"input_tokens": 100 + i, "cache_creation_input_tokens": 10,
                                                      "cache_read_input_tokens": 50, "output_tokens": out_tokens}},
            **extra}


def turn_end(i: int, session: str, minute: int) -> Dict[str, Any]:
    return {"type": "system", "subtype": "turn_duration", "uuid": f"s-{session[-1]}-{i}", "sessionId": session,
            "cwd": PROJECT_CWD, "timestamp": stamp(minute, 40)}


def claude_turns(session: str, first: int, n: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for k in range(n):
        out += [user(first + k, session, first + k), assistant(first + k, session, first + k, 20 + k),
                turn_end(first + k, session, first + k)]
    return out


def claude_main(turns: int = 4) -> bytes:
    return jl(*claude_turns(MAIN, 0, turns))


def claude_subagent() -> bytes:
    return jl(assistant(50, MAIN, 6, 7, tool="Read"), assistant(51, MAIN, 7, 9, tool="Grep"))


def claude_partial() -> bytes:
    return jl(user(0, MAIN, 0), assistant(0, MAIN, 0, 20)) + b'{"type": "user", "uuid": "u-1-9", "timest'


def claude_fork_child() -> bytes:
    copied = [dict(r, forkedFrom={"sessionId": MAIN, "messageUuid": r["uuid"]}) for r in claude_turns(MAIN, 0, 1)[:2]]
    return jl(*copied, *claude_turns(FORKED, 10, 1))


def claude_rewritten() -> bytes:
    return jl(*claude_turns(MAIN, 20, 2), *claude_turns(MAIN, 30, 3))


def codex_rollout() -> bytes:
    def tokens(inp: int, cached: int, out: int) -> Dict[str, Any]:
        return {"type": "event_msg", "timestamp": stamp(2, 30), "payload": {
            "type": "token_count", "info": {"total_token_usage": {
                "input_tokens": inp, "cached_input_tokens": cached, "output_tokens": out,
                "reasoning_output_tokens": 0}}}}
    return jl(
        {"type": "session_meta", "timestamp": stamp(0), "payload": {"cwd": PROJECT_CWD, "cli_version": "0.40.0"}},
        {"type": "turn_context", "timestamp": stamp(1), "payload": {"model": "gpt-5-codex"}},
        {"type": "response_item", "timestamp": stamp(1, 30), "payload": {
            "type": "function_call", "name": "shell", "call_id": "c1"}},
        tokens(1000, 200, 50), dict(tokens(2500, 600, 120), timestamp=stamp(4)),
        {"type": "event_msg", "timestamp": stamp(5), "payload": {"type": "task_complete"}})
