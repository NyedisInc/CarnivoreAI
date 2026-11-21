
from __future__ import annotations

from datetime import datetime
from typing import List, NamedTuple, Optional, Tuple

from src.core.attention.toast_facts import ToastFacts
from src.core.attention.transcript_facts import BLOCKING_TOOL_NAMES, FACTS_TAIL_BYTES, FACTS_WIDE_TAIL_BYTES
from src.core.attention.transcript_records import TURN_END_INTERRUPT
from src.core.timeline.boundary import WindowView
from src.core.timeline.fold import ConvState
from src.core.timeline.fold_types import LaunchRec


class Window(NamedTuple):

    bound: int
    whole: bool
    view: WindowView
    assistant_at: Optional[datetime]
    prompt_seen: bool
    outside: bool


def window_at(state: ConvState, bound: int) -> Window:
    bound = max(bound, 0)
    whole = state.whole and bound == 0
    view = state.window_view(bound)
    assistant_at = state.newest_assistant.within(bound)
    prompt_seen = state.prompt_seen.within(bound) is True
    outside = (view.outside and view.kind == TURN_END_INTERRUPT) or (
        not whole and view.kind is None and assistant_at is None and not prompt_seen
    )
    return Window(bound, whole, view, assistant_at, prompt_seen, outside)


def tail_bounds(state: ConvState, size: int, tail_bytes: int, wide_tail_bytes: int) -> Tuple[int, int]:
    return (state.starts.window_start_at(size - tail_bytes, tail_bytes),
            state.starts.window_start_at(size - wide_tail_bytes, wide_tail_bytes))


def choose_window(
    state: ConvState, size: Optional[int], tail_bytes: int = FACTS_TAIL_BYTES, wide_tail_bytes: int = FACTS_WIDE_TAIL_BYTES
) -> Window:
    size = state.cursor if size is None else size
    narrow_start, wide_start = tail_bounds(state, size, tail_bytes, wide_tail_bytes)
    narrow = window_at(state, narrow_start)
    if narrow.outside and wide_tail_bytes > tail_bytes:
        return window_at(state, wide_start)
    return narrow


def open_launches(state: ConvState, bound: int) -> List[LaunchRec]:
    return [launch for launch in state.launches.values() if launch.offset >= bound and not launch.completed(state.notified, bound)]


def blocked_tool(state: ConvState, bound: int, notes: List[str]) -> Optional[str]:
    call = state.blocked.within(bound)
    if call is None:
        return None
    answered = isinstance(call.call_id, str) and bool(call.call_id) and state.result_at.get(call.call_id, -1) >= bound
    name = call.name if isinstance(call.name, str) and call.name else None
    if not name or answered:
        return None
    if name in BLOCKING_TOOL_NAMES:
        return name
    notes.append(
        "the window ends on an unanswered call to " + name
        + ", which is a tool still running and not a question for the user"
    )
    return None


def toast_facts(state: ConvState, bound: int) -> ToastFacts:
    call = state.toast_call.within(bound)
    pending = None
    if call is not None:
        unanswered = not (isinstance(call.call_id, str) and state.main_result_at.get(call.call_id, -1) >= bound)
        pending = call if unanswered and call.tool else None
    return ToastFacts(
        last_text=state.toast_text.within(bound),
        pending_tool=pending.tool if pending else None,
        pending_target=pending.target if pending else None,
    )
