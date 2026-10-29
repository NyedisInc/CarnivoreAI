
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from src.core.attention.toast_facts import ToastFacts, extract_toast_facts
from src.core.attention.transcript_contract import against_contract
from src.core.attention.usage_limit import (
    UsageLimit, active_usage_limit, usage_limit_from_record,
)
from src.core.attention.transcript_records import (
    TURN_END_SUBTYPE,
    TURN_END_DURATION,
    TURN_END_INTERRUPT,
    TURN_END_NO_MODEL_TURN,
    ENQUEUE_OPERATION,
    TASK_NOTIFICATION_MARKER,
    QUEUED_COMMAND_ATTACHMENT,
    _record_text,
    _retired_ids,
    _is_task_notification,
    _is_real_user_prompt,
    _is_interrupt,
    _is_resume_placeholder,
    _is_local_command,
)
from src.core.attention.turn_counts import (
    KIND_WORKFLOW,
    TURN_END_COUNTED_KINDS,
    async_launch,
    content_blocks,
    decode_turn_end_counts,
    stopped_task_id,
)
from src.core.claude_title_sync import read_tail_records
from src.core.mcp_health.fold import McpEvent, extract_mcp_events, window_start
from src.core.mcp_health.history import merge_mcp_history
from src.core.session_status_seed_records import parse_timestamp


FACTS_FOUND: str = "found"

FACTS_NO_RECORD: str = "no_record"

# could not be read
FACTS_UNREADABLE: str = "unreadable"

FACTS_SHAPE_UNRECOGNIZED: str = "shape_unrecognized"

FACTS_TAIL_BYTES: int = 256 * 1024

FACTS_WIDE_TAIL_BYTES: int = 4 * 1024 * 1024

# nothing at all
BLOCKING_TOOL_NAMES: frozenset = frozenset({"AskUserQuestion", "ExitPlanMode"})

BOOKKEEPING_RECORD_TYPES: frozenset = frozenset(
    {
        "queue-operation",
        "attachment",
        "last-prompt",
        "custom-title",
        "ai-title",
        "agent-name",
        "mode",
        "permission-mode",
        "atis-latch",
        "bridge-session",
        "history-suppression",
        "pr-link",
        "frame-link",
        "cost-state",
    }
)

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


def _later(left: Optional[datetime], right: Optional[datetime]) -> Optional[datetime]:
    if left is None:
        return right
    if right is None:
        return left
    return right if right > left else left


def classify_transcript_records(
    records: Sequence[Any],
    *,
    now: Optional[datetime] = None,
    window_is_whole_file: bool = False,
) -> TranscriptFacts:
    turn_end: Optional[Dict[str, Any]] = None
    pending: Optional[int] = None
    pending_present = False
    workflows: Optional[int] = None
    notes: List[str] = []
    newest_append_at: Optional[datetime] = None
    newest_assistant_at: Optional[datetime] = None
    newest_user_prompt_at: Optional[datetime] = None
    newest_enqueue_at: Optional[datetime] = None
    launches: Dict[str, Dict[str, Optional[str]]] = {}
    launch_at: Dict[str, Optional[datetime]] = {}
    notified: Set[str] = set()
    answered_tool_use_ids: Set[str] = set()
    last_meaningful: Optional[Dict[str, Any]] = None
    turn_end_kind: Optional[str] = None
    before_interrupt: Optional[tuple] = None
    turn_tool_ids: Set[str] = set()
    model_prompt_seen = False
    newest_local_command_at: Optional[datetime] = None
    retired_since_turn_end = False
    boundary_outside_window = False
    limit_hit: Optional[UsageLimit] = None

    for record in records or ():
        if not isinstance(record, dict):
            continue
        if record.get("type") not in BOOKKEEPING_RECORD_TYPES:
            last_meaningful = record
        at = parse_timestamp(record.get("timestamp"))
        newest_append_at = _later(newest_append_at, at)
        kind = record.get("type")

        if kind == "system":
            if record.get("subtype") == TURN_END_SUBTYPE:
                turn_end = record
                turn_end_kind = TURN_END_DURATION
                before_interrupt = None
                turn_tool_ids = set()
                retired_since_turn_end = False
                boundary_outside_window = False
                pending, pending_present, workflows, notes = (
                    decode_turn_end_counts(record)
                )
                if pending == 0 and workflows == 0:
                    launches = {
                        key: launch
                        for key, launch in launches.items()
                        if launch["kind"] not in TURN_END_COUNTED_KINDS
                    }
            elif _is_local_command(record):
                newest_local_command_at = _later(newest_local_command_at, at)
            continue

        if kind == "assistant":
            if _is_resume_placeholder(record):
                continue
            newest_assistant_at = _later(newest_assistant_at, at)
            if record.get("isSidechain") is not True:
                limit_hit = usage_limit_from_record(record)
            for block in content_blocks(record, "tool_use"):
                if isinstance(block.get("id"), str) and block.get("id"):
                    turn_tool_ids.add(block["id"])
            continue

        if kind == "queue-operation":
            if record.get("operation") == ENQUEUE_OPERATION:
                content = record.get("content")
                if isinstance(content, str) and content.lstrip().startswith(
                    TASK_NOTIFICATION_MARKER
                ):
                    newest_enqueue_at = _later(newest_enqueue_at, at)
                    retired = _retired_ids(content)
                    notified.update(retired)
                    retired_since_turn_end = retired_since_turn_end or bool(retired)
            continue

        if kind == "attachment":
            attachment = record.get("attachment")
            if (
                isinstance(attachment, dict)
                and attachment.get("type") == QUEUED_COMMAND_ATTACHMENT
                and isinstance(attachment.get("prompt"), str)
            ):
                retired = _retired_ids(attachment["prompt"])
                notified.update(retired)
                retired_since_turn_end = retired_since_turn_end or bool(retired)
            continue

        if kind != "user":
            continue

        for block in content_blocks(record, "tool_result"):
            candidate = block.get("tool_use_id")
            if isinstance(candidate, str) and candidate:
                answered_tool_use_ids.add(candidate)

        if _is_task_notification(record):
            retired = _retired_ids(_record_text(record))
            notified.update(retired)
            retired_since_turn_end = retired_since_turn_end or bool(retired)
            continue

        stopped = stopped_task_id(record)
        if stopped is not None:
            notified.add(stopped)
            retired_since_turn_end = True
            continue

        launch = async_launch(record)
        if launch is not None:
            launches[str(launch["key"])] = launch
            launch_at[str(launch["key"])] = at
            continue

        if _is_interrupt(record):
            if turn_tool_ids <= answered_tool_use_ids:
                before_interrupt = (
                    turn_end, turn_end_kind, pending, pending_present, workflows
                )
                if turn_end is None:
                    if window_is_whole_file:
                        pending, workflows = 0, 0
                    else:
                        pending, workflows = None, None
                        boundary_outside_window = True
                elif retired_since_turn_end:
                    if pending:
                        pending = None
                    if workflows:
                        workflows = None
                turn_end = record
                turn_end_kind = TURN_END_INTERRUPT
                pending_present = False
                turn_tool_ids = set()
        elif _is_local_command(record):
            newest_local_command_at = _later(newest_local_command_at, at)
        elif _is_real_user_prompt(record):
            model_prompt_seen = True
            if before_interrupt is not None:
                turn_end, turn_end_kind, pending, pending_present, workflows = (
                    before_interrupt
                )
                before_interrupt = None
                boundary_outside_window = False

        if _is_real_user_prompt(record):
            newest_user_prompt_at = _later(newest_user_prompt_at, at)

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
        ids = {launch["task_id"], launch["tool_use_id"]} - {None}
        if ids & notified:
            continue
        if launch["kind"] in TURN_END_COUNTED_KINDS:
            open_async += 1
            open_workflows += launch["kind"] == KIND_WORKFLOW
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
    """Read the tail of one transcript and say what it means.

    Description: the I/O half, and it NEVER RAISES. The read is
      ``claude_title_sync.read_tail_records``, the one bounded transcript
      reader in this codebase, at the wider window this caller needs; no
      second reader is built here. It opens the window ON A RECORD
      BOUNDARY, so a blocking record wider than ``tail_bytes`` is read
      rather than mistaken for a partial line and discarded, and it skips
      any line that does not parse, which is what makes a TORN final line
      from a live writer normal rather than a failure: the good records
      around it still count, and only a file that could not be OPENED
      refuses. So the mapping is two-way, not three-way: a refusal (no
      path, absent, unreadable)
      becomes :data:`FACTS_UNREADABLE` carrying the reader's own
      sentence, and anything read goes to the pure classifier, then
      through the shape contract (:data:`FACTS_SHAPE_UNRECOGNIZED`).

      ONE WIDER READ, for one shape only: the window ends on an Esc
      interrupt, did not start at byte 0, and holds no turn end before
      the interrupt, so its count came back unknown. The file is read
      once more at ``wide_tail_bytes`` to find that turn end; if it is
      still not there the count stays unknown and the turn is not rest.
    Inputs: path (str | None) - the conversation jsonl. tail_bytes (int)
      - the hard cap on the normal read. now (datetime | None) - the
      caller's clock, passed through to the classifier. wide_tail_bytes
      (int) - the hard cap on the one wider read.
    Output: TranscriptFacts.
    Example:
      read_transcript_facts('/x/abc.jsonl').pending_background_agents -> 3
    """
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
