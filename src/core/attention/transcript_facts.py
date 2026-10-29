
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Tuple

from src.core.attention.transcript_walk import WindowWalk
from src.core.attention.toast_facts import ToastFacts, extract_toast_facts
from src.core.attention.transcript_contract import against_contract
from src.core.attention.usage_limit import UsageLimit, active_usage_limit
from src.core.attention.transcript_records import TURN_END_INTERRUPT, TURN_END_NO_MODEL_TURN
from src.core.attention.turn_counts import KIND_WORKFLOW, TURN_END_COUNTED_KINDS, content_blocks
from src.core.claude_title_sync import read_tail_records
from src.core.mcp_health.fold import McpEvent, extract_mcp_events, window_start
from src.core.mcp_health.history import merge_mcp_history
from src.core.session_status_seed_records import parse_timestamp


FACTS_FOUND: str = "found"

FACTS_NO_RECORD: str = "no_record"

FACTS_UNREADABLE: str = "unreadable"

FACTS_SHAPE_UNRECOGNIZED: str = "shape_unrecognized"

FACTS_TAIL_BYTES: int = 256 * 1024

FACTS_WIDE_TAIL_BYTES: int = 4 * 1024 * 1024

BLOCKING_TOOL_NAMES: frozenset = frozenset({"AskUserQuestion", "ExitPlanMode"})


@dataclass(frozen=True)
class TranscriptFacts:

    verdict: str
    pending_background_agents: Optional[int] = None
    pending_field_present: bool = False
    pending_workflows: Optional[int] = None
    turn_end_at: Optional[datetime] = None
    newest_assistant_at: Optional[datetime] = None
    newest_append_at: Optional[datetime] = None
    blocked_on_tool: Optional[str] = None
    queued_reinvoke: bool = False
    open_async_agents: int = 0
    open_background_tasks: int = 0
    open_background_launched_at: Tuple[Optional[datetime], ...] = ()
    open_workflows: int = 0
    newest_user_prompt_at: Optional[datetime] = None
    detail: str = ""
    turn_end_kind: Optional[str] = None
    turn_end_outside_window: bool = False
    toast_facts: Optional[ToastFacts] = None
    shape_problems: Tuple[str, ...] = ()
    absent: bool = False
    mcp_events: Tuple[McpEvent, ...] = ()
    mcp_window_from: Optional[datetime] = None
    usage_limit: Optional[UsageLimit] = None

    @property
    def found(self) -> bool:
        return self.verdict == FACTS_FOUND


def classify_transcript_records(
    records: Sequence[Any],
    *,
    now: Optional[datetime] = None,
    window_is_whole_file: bool = False,
) -> TranscriptFacts:
    walk = WindowWalk(window_is_whole_file=window_is_whole_file)
    for record in records or ():
        walk.feed(record)
    turn_end = walk.turn_end
    pending = walk.pending
    pending_present = walk.pending_present
    workflows = walk.workflows
    notes = walk.notes
    newest_append_at = walk.newest_append_at
    newest_assistant_at = walk.newest_assistant_at
    newest_user_prompt_at = walk.newest_user_prompt_at
    newest_enqueue_at = walk.newest_enqueue_at
    launches = walk.launches
    launch_at = walk.launch_at
    notified = walk.notified
    answered_tool_use_ids = walk.answered_tool_use_ids
    last_meaningful = walk.last_meaningful
    turn_end_kind = walk.turn_end_kind
    model_prompt_seen = walk.model_prompt_seen
    newest_local_command_at = walk.newest_local_command_at
    boundary_outside_window = walk.boundary_outside_window
    limit_hit = walk.limit_hit

    turn_end_at = (
        parse_timestamp(turn_end.get("timestamp")) if turn_end is not None else None
    )
    if (
        turn_end is None
        and window_is_whole_file
        and newest_assistant_at is None
        and not model_prompt_seen
        and not launches
        and newest_local_command_at is not None
    ):
        turn_end_kind = TURN_END_NO_MODEL_TURN
        turn_end_at = newest_local_command_at
        pending, workflows = 0, 0

    blocked_on_tool: Optional[str] = None
    if last_meaningful is not None and last_meaningful.get("type") == "assistant":
        blocks = content_blocks(last_meaningful, "tool_use")
        block = blocks[-1] if blocks else None
        if block is not None:
            block_id = block.get("id")
            answered = isinstance(block_id, str) and block_id in answered_tool_use_ids
            name = block.get("name")
            name = name if isinstance(name, str) and name else None
            if name and not answered:
                if name in BLOCKING_TOOL_NAMES:
                    blocked_on_tool = name
                else:
                    notes.append(
                        "the window ends on an unanswered call to "
                        + name
                        + ", which is a tool still running and not a "
                        "question for the user"
                    )

    limit_now = active_usage_limit(limit_hit, now or datetime.now(timezone.utc))
    if limit_now is not None:
        pending, workflows = None, None
        newest_enqueue_at = None
        notes.append(
            "a usage limit is in force (" + limit_now.kind + "), so queued "
            "completions and pending agent counts are not read as work"
        )

    queued_reinvoke = bool(
        newest_enqueue_at is not None
        and turn_end_at is not None
        and newest_enqueue_at > turn_end_at
    )
    if queued_reinvoke:
        notes.append(
            "a background agent's completion is queued and newer than "
            "the last turn end, so claude is about to be re-invoked "
            "with nobody asking it to"
        )

    open_async = 0
    open_background = 0
    open_background_at: List[Optional[datetime]] = []
    open_workflows = 0
    for key, launch in launches.items():
        ids = {launch.task_id, launch.tool_use_id} - {None}
        if ids & notified:
            continue
        if launch.kind in TURN_END_COUNTED_KINDS:
            open_async += 1
            open_workflows += launch.kind == KIND_WORKFLOW
        else:
            open_background += 1
            open_background_at.append(launch_at.get(key))
    if open_async:
        notes.append(
            str(open_async)
            + " background agent or workflow launch(es) in the window have no "
            "completion in it, which is a floor and not a total"
        )
    if open_background:
        notes.append(
            str(open_background)
            + " background shell or monitor launch(es) in the window have no "
            "completion, stop or resume notice in it, which is a floor and "
            "not a total"
        )
    if blocked_on_tool:
        notes.append(
            "the window ends on an unanswered "
            + blocked_on_tool
            + ", so claude is waiting on the user"
        )

    if turn_end_kind is None:
        verdict = FACTS_NO_RECORD
        head = (
            "the transcript tail that was read holds no turn-end "
            "record, so the number of pending background agents is "
            "unknown rather than zero"
        )
    else:
        verdict = FACTS_FOUND
        if pending is None:
            head = "a turn-end record was read and it names no usable agent count"
        else:
            head = (
                "a turn-end record was read and "
                + str(pending)
                + " background agent(s) were pending when the turn ended"
            )
        if turn_end_kind == TURN_END_INTERRUPT:
            head = "the turn was stopped with an interrupt (Esc); " + head
        elif turn_end_kind == TURN_END_NO_MODEL_TURN:
            head = (
                "the whole transcript holds only local slash commands, so "
                "no model turn has run and nothing is pending"
            )
        if workflows:
            head += (
                "; " + str(workflows) + " workflow(s) were pending when the "
                "turn ended"
            )

    return TranscriptFacts(
        verdict=verdict,
        pending_background_agents=pending,
        pending_field_present=pending_present,
        pending_workflows=workflows,
        turn_end_at=turn_end_at,
        newest_assistant_at=newest_assistant_at,
        newest_append_at=newest_append_at,
        blocked_on_tool=blocked_on_tool,
        queued_reinvoke=queued_reinvoke,
        open_async_agents=open_async,
        open_background_tasks=open_background,
        open_background_launched_at=tuple(open_background_at),
        open_workflows=open_workflows,
        newest_user_prompt_at=newest_user_prompt_at,
        detail="; ".join([head] + notes),
        turn_end_kind=turn_end_kind,
        turn_end_outside_window=(
            boundary_outside_window and turn_end_kind == TURN_END_INTERRUPT
        ) or (
            not window_is_whole_file
            and turn_end_kind is None
            and newest_assistant_at is None
            and not model_prompt_seen
        ),
        toast_facts=extract_toast_facts(records),
        mcp_events=extract_mcp_events(records),
        mcp_window_from=window_start(records),
        usage_limit=limit_now,
    )


def read_transcript_facts(
    path: Optional[str],
    *,
    tail_bytes: int = FACTS_TAIL_BYTES,
    now: Optional[datetime] = None,
    wide_tail_bytes: int = FACTS_WIDE_TAIL_BYTES,
) -> TranscriptFacts:
    read = read_tail_records(path, tail_bytes=tail_bytes)
    if not read.readable:
        return TranscriptFacts(
            verdict=FACTS_UNREADABLE,
            detail=read.detail or "the transcript could not be read",
        )
    facts = classify_transcript_records(
        read.records, now=now, window_is_whole_file=read.scanned_from == 0
    )
    used = read
    if (
        facts.turn_end_outside_window and wide_tail_bytes > tail_bytes
    ):
        wide = read_tail_records(path, tail_bytes=wide_tail_bytes)
        if wide.readable:
            used = wide
            facts = classify_transcript_records(
                wide.records, now=now, window_is_whole_file=wide.scanned_from == 0
            )
    facts = dataclasses.replace(facts, mcp_events=merge_mcp_history(
        path, facts.mcp_events, scanned_from=used.scanned_from, file_size=used.file_size
    ))
    return against_contract(facts, used.records, FACTS_SHAPE_UNRECOGNIZED)
