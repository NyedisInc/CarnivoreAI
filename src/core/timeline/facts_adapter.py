
from __future__ import annotations

from datetime import datetime, timezone
from typing import FrozenSet, List, NamedTuple, Optional

from src.core.attention.transcript_contract import with_problems
from src.core.attention.transcript_facts import (
    FACTS_FOUND,
    FACTS_NO_RECORD,
    FACTS_SHAPE_UNRECOGNIZED,
    FACTS_TAIL_BYTES,
    FACTS_WIDE_TAIL_BYTES,
    TranscriptFacts,
)
from src.core.attention.transcript_records import TURN_END_INTERRUPT, TURN_END_NO_MODEL_TURN
from src.core.attention.turn_counts import KIND_WORKFLOW, TURN_END_COUNTED_KINDS
from src.core.attention.usage_limit import UsageLimit, active_usage_limit
from src.core.timeline.fold import ConvState
from src.core.timeline.fold_types import LaunchRec
from src.core.timeline.facts_window import Window, blocked_tool, choose_window, open_launches, toast_facts, window_at

class WholeFileUnavailableError(ValueError):
    pass


TURN_END_FIELDS: FrozenSet[str] = frozenset({
    "verdict", "pending_background_agents", "pending_field_present", "pending_workflows", "turn_end_at",
    "turn_end_kind", "turn_end_outside_window", "queued_reinvoke", "queued_reinvoke_at", "detail",
})


class TurnFields(NamedTuple):

    kind: Optional[str]
    at: Optional[datetime]
    pending: Optional[int]
    present: bool
    workflows: Optional[int]


class WindowFields(NamedTuple):

    blocked: Optional[str]
    queued: bool
    enqueue_at: Optional[datetime]
    limit: Optional[UsageLimit]


def _head_sentence(kind: Optional[str], pending: Optional[int], workflows: Optional[int]) -> str:
    if kind is None:
        return (
            "the transcript tail that was read holds no turn-end record, so the number of pending background "
            "agents is unknown rather than zero"
        )
    if pending is None:
        head = "a turn-end record was read and it names no usable agent count"
    else:
        head = "a turn-end record was read and " + str(pending) + " background agent(s) were pending when the turn ended"
    if kind == TURN_END_INTERRUPT:
        head = "the turn was stopped with an interrupt (Esc); " + head
    elif kind == TURN_END_NO_MODEL_TURN:
        head = "the whole transcript holds only local slash commands, so no model turn has run and nothing is pending"
    if workflows:
        head += "; " + str(workflows) + " workflow(s) were pending when the turn ended"
    return head


def _turn_fields(state: ConvState, win: Window) -> TurnFields:
    boundary = state.boundary
    fields = TurnFields(
        boundary.kind if boundary else None, boundary.at if boundary else None,
        boundary.pending if boundary else None, boundary.pending_present if boundary else False,
        boundary.workflows if boundary else None,
    )
    local_at = state.newest_local_command.within(win.bound)
    anything_launched = any(launch.offset >= win.bound for launch in state.launches.values())
    if fields.kind is None and win.whole and win.assistant_at is None and not win.prompt_seen and not anything_launched and local_at:
        return TurnFields(TURN_END_NO_MODEL_TURN, local_at, 0, False, 0)
    return fields


def _window_fields(state: ConvState, win: Window, turn: TurnFields, now: Optional[datetime], notes: List[str]) -> WindowFields:
    blocked = blocked_tool(state, win.bound, notes)
    enqueue_at = state.newest_enqueue.within(win.bound)
    limit = active_usage_limit(state.usage_limit_hit.within(win.bound), now or datetime.now(timezone.utc))
    if limit is not None:
        enqueue_at = None
        notes.append(
            "a usage limit is in force (" + limit.kind + "), so queued completions and pending agent counts are not "
            "read as work"
        )
    queued = bool(enqueue_at is not None and turn.at is not None and enqueue_at > turn.at)
    if queued:
        notes.append(
            "a background agent's completion is queued and newer than the last turn end, so claude is about to be "
            "re-invoked with nobody asking it to"
        )
    return WindowFields(blocked, queued, enqueue_at, limit)


def _launch_notes(counted: List[LaunchRec], background: List[LaunchRec], blocked: Optional[str]) -> List[str]:
    notes: List[str] = []
    if counted:
        notes.append(
            str(len(counted)) + " background agent or workflow launch(es) in the window have no completion in it, "
            "which is a floor and not a total"
        )
    if background:
        notes.append(
            str(len(background)) + " background shell or monitor launch(es) in the window have no completion, stop "
            "or resume notice in it, which is a floor and not a total"
        )
    if blocked:
        notes.append("the window ends on an unanswered " + blocked + ", so claude is waiting on the user")
    return notes


def facts_from_window(
    state: ConvState, win: Window, *, now: Optional[datetime] = None, file_size: Optional[int] = None,
    fresh_history: bool = False,
) -> TranscriptFacts:
    turn = _turn_fields(state, win)
    notes: List[str] = list(state.machine.notes)
    fields = _window_fields(state, win, turn, now, notes)
    if fields.limit is not None:
        turn = turn._replace(pending=None, workflows=None)
    opened = open_launches(state, win.bound)
    counted = [launch for launch in opened if launch.kind in TURN_END_COUNTED_KINDS]
    background = [launch for launch in opened if launch.kind not in TURN_END_COUNTED_KINDS]
    notes.extend(_launch_notes(counted, background, fields.blocked))
    if fresh_history:
        state.mcp_log.forget_history()
    facts = TranscriptFacts(
        verdict=FACTS_NO_RECORD if turn.kind is None else FACTS_FOUND,
        pending_background_agents=turn.pending,
        pending_field_present=turn.present,
        pending_workflows=turn.workflows,
        turn_end_at=turn.at,
        newest_assistant_at=win.assistant_at,
        newest_append_at=state.newest_append.within(win.bound),
        blocked_on_tool=fields.blocked,
        queued_reinvoke=fields.queued,
        queued_reinvoke_at=fields.enqueue_at if fields.queued else None,
        open_async_agents=len(counted),
        open_background_tasks=len(background),
        open_background_launched_at=tuple(launch.at for launch in background),
        open_background_task_ids=tuple(launch.task_id for launch in background),
        open_workflows=sum(1 for launch in counted if launch.kind == KIND_WORKFLOW),
        newest_user_prompt_at=state.newest_prompt.within(win.bound),
        detail="; ".join([_head_sentence(turn.kind, turn.pending, turn.workflows)] + notes),
        turn_end_kind=turn.kind,
        turn_end_outside_window=win.outside,
        toast_facts=toast_facts(state, win.bound),
        mcp_events=state.mcp_log.joined(win.bound, state.cursor if file_size is None else file_size),
        mcp_window_from=state.earliest_main.within(win.bound),
        usage_limit=fields.limit,
    )
    return with_problems(facts, state.shape.problems_within(win.bound), FACTS_SHAPE_UNRECOGNIZED)


def facts_from_state(
    state: ConvState, *, now: Optional[datetime] = None, size: Optional[int] = None,
    window_start: Optional[int] = None, tail_bytes: int = FACTS_TAIL_BYTES, wide_tail_bytes: int = FACTS_WIDE_TAIL_BYTES,
    fresh_history: bool = False,
) -> TranscriptFacts:
    if window_start is not None:
        win = window_at(state, window_start)
    elif size is not None:
        win = choose_window(state, size, tail_bytes, wide_tail_bytes)
    elif state.bounded:
        raise WholeFileUnavailableError(
            "a state with retain_bytes=%d keeps only what a window can reach; pass size= or window_start=, or fold with "
            "retain_bytes=None for a whole-file answer" % state.retain_bytes
        )
    else:
        win = window_at(state, 0)
    return facts_from_window(state, win, now=now, file_size=size, fresh_history=fresh_history)
