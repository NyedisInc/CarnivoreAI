
from __future__ import annotations

from typing import Any

from src.core.mcp import route_adapters as ra, session_target
from src.core.mcp.common import ToolError
from src.core.timeline.model import LEVEL_TRACE, LEVEL_TALK, NO_TURN_BOUND, Kind

DEFAULT_ROWS = 50
MAX_ROWS = 100


def _whole(args: dict, key: str, low: int, high: int) -> Any:
    value = args.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ToolError(f"{key} must be a whole number from {low} to {high}")
    return value


async def _state(call: ra.Call) -> Any:
    answer = await call.route(call.request, call.session_uuid)
    target = call.target
    sleeper = getattr(call.request.app.state, "auto_sleeper", None)
    if isinstance(answer, dict) and sleeper is not None and target is not None and target.live:
        verdict = sleeper.verdict_for(target.info.session.id)
        if verdict is not None:
            answer = {**answer, "auto_sleep": verdict.model_dump(mode="json")}
    return answer


async def _events(call: ra.Call) -> Any:
    args = call.args
    names = args.get("kinds")
    if names is not None and (not isinstance(names, list) or not all(isinstance(n, str) for n in names)):
        raise ToolError("kinds must be a list of event kind names")
    unknown = sorted(n for n in names or [] if n not in {k.value for k in Kind})
    if unknown:
        raise ToolError(f"unknown event kinds: {', '.join(unknown)}")
    after, thread = args.get("after"), args.get("thread")
    if any(v is not None and not isinstance(v, str) for v in (after, thread)):
        raise ToolError("after and thread must be text")
    shown = args.get("include_abandoned", False)
    if not isinstance(shown, bool):
        raise ToolError("include_abandoned must be true or false")
    return await call.route(
        call.request, call.session_uuid, after=after, before_turn=_whole(args, "before_turn", 0, NO_TURN_BOUND),
        limit=_whole(args, "limit", 1, MAX_ROWS) or DEFAULT_ROWS, kinds=",".join(names) if names else None, thread=thread,
        turn=_whole(args, "turn", 0, NO_TURN_BOUND), level=_whole(args, "level", LEVEL_TALK, LEVEL_TRACE), conv=None,
        include_abandoned=shown)


SPECS = (
    ra.RouteTool(
        name="session_events_list", route="src.api.timeline.routes:timeline_events", gate=ra.READ, redact=True,
        reach=session_target.STORED, needs_uuid=True,
        description="A page of a Claude Code session's typed events (prompt, reply, tool_call, turn_end, ...), live or asleep: kinds, "
                    "positions and identifiers, no conversation text. Pass after (the next cursor of the last page) to read forward; "
                    "without it the newest turns come first and next_before pages older ones. level 1 talk, 2 work (default), 3 trace. "
                    "Refused while session chat is off.",
        properties={
            "after": {"type": "string", "description": "the next cursor of a previous page"},
            "before_turn": {"type": "integer", "minimum": 0, "description": "next_before of a previous page"},
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_ROWS,
                      "description": "page size: TURNS on a backward page (no after), EVENTS on a forward page (after given); default 50"},
            "kinds": {"type": "array", "items": {"type": "string", "enum": [k.value for k in Kind]}},
            "thread": {"type": "string", "description": "main, side, wf:<id> or agent:<id>"},
            "turn": {"type": "integer", "minimum": 0},
            "level": {"type": "integer", "minimum": LEVEL_TALK, "maximum": LEVEL_TRACE},
            "include_abandoned": {"type": "boolean", "description": "also the lines of branches a rewind left behind (flagged abandoned)"},
        },
        invoke=_events, example={"limit": 5},
    ),
    ra.RouteTool(
        name="session_state_get", route="src.api.timeline.routes:timeline_state", gate=ra.READ, redact=True,
        reach=session_target.STORED, needs_uuid=True,
        description="A Claude Code session's state from its transcript: open turn, last turn end, open background agents and workflows, a q"
                    "ueued re-invoke, newest prompt and reply times. A live session adds the lights' answer and auto_sleep: why auto sleep "
                    "has not slept it (open_in_window, idle_waiting, listening, work_running, keep_awake_list), idle_since, threshold_minut"
                    "es. Refused while session chat is off.",
        invoke=_state, example={},
    ),
)

READ_TOOLS, WRITE_TOOLS, UNGATED_WRITES = ra.tables(SPECS)
