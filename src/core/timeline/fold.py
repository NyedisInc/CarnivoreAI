
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from src.core.attention.toast_facts import extract_toast_facts
from src.core.attention.transcript_records import (
    BOOKKEEPING_RECORD_TYPES,
    ENQUEUE_OPERATION,
    QUEUED_COMMAND_ATTACHMENT,
    TASK_NOTIFICATION_MARKER,
    TURN_END_DURATION,
    TURN_END_SUBTYPE,
    is_interrupt,
    is_local_command,
    is_real_user_prompt,
    is_resume_placeholder,
    is_task_notification,
    record_text,
    retired_ids,
)
from src.core.attention.turn_counts import (
    TURN_END_COUNTED_KINDS,
    async_launch,
    content_blocks,
    decode_turn_end_counts,
    stopped_task_id,
)
from src.core.attention.usage_limit import UsageLimit, usage_limit_from_record
from src.core.mcp_health.fold import McpEvent, scan_record_located
from src.core.session_status_seed_records import parse_timestamp
from src.core.timeline.boundary import (
    OP_CALL,
    OP_INTERRUPT,
    OP_PROMPT,
    OP_RESULT,
    OP_RETIRE,
    TurnLog,
    TurnMachine,
    TurnSnap,
    WindowView,
)
from src.core.timeline.fold_types import BlockedCall, LaunchRec, QueuedMessage, ToastCall
from src.core.timeline.mcp_log import MAX_OPEN_CALLS, McpLog
from src.core.timeline.model import Kind, TimelineEvent
from src.core.timeline.shape import ShapeLedger
from src.core.timeline.stamps import (
    WINDOW_RETENTION_BYTES,
    RecordStarts,
    Seen,
    SuffixExtreme,
    earliest,
    newest,
    trim_all,
)

MAX_QUEUED: int = 200
MAX_NOTIFIED: int = 4096
MAX_RESULT_IDS: int = 8192
TRIM_EVERY: int = 256
OP_ENQUEUE, OP_DEQUEUE, OP_REMOVE, OP_POP_ALL = "enqueue", "dequeue", "remove", "popAll"


@dataclass
class ConvState:

    conv: str
    coverage_start: int = 0
    cursor: int = 0
    leaf_uuid: Optional[str] = None
    open_turn: Optional[int] = None
    title: Optional[str] = None
    launches: Dict[str, LaunchRec] = field(default_factory=dict)
    notified: Dict[str, int] = field(default_factory=dict)
    result_at: Dict[str, int] = field(default_factory=dict)
    main_result_at: Dict[str, int] = field(default_factory=dict)
    queued: List[QueuedMessage] = field(default_factory=list)
    machine: TurnMachine = field(default_factory=TurnMachine)
    turn_log: TurnLog = field(default_factory=TurnLog)
    mcp_log: McpLog = field(default_factory=McpLog)
    mcp_open_calls: Dict[str, str] = field(default_factory=dict)
    mcp_origins: Dict[str, int] = field(default_factory=dict)
    shape: ShapeLedger = field(default_factory=ShapeLedger)
    starts: RecordStarts = field(default_factory=RecordStarts)
    newest_append: SuffixExtreme = field(default_factory=newest)
    newest_assistant: SuffixExtreme = field(default_factory=newest)
    newest_prompt: SuffixExtreme = field(default_factory=newest)
    newest_enqueue: SuffixExtreme = field(default_factory=newest)
    newest_reply: SuffixExtreme = field(default_factory=newest)
    newest_local_command: SuffixExtreme = field(default_factory=newest)
    earliest_main: SuffixExtreme = field(default_factory=earliest)
    prompt_seen: Seen[bool] = field(default_factory=Seen)
    usage_limit_hit: Seen[UsageLimit] = field(default_factory=Seen)
    blocked: Seen[BlockedCall] = field(default_factory=Seen)
    toast_text: Seen[str] = field(default_factory=Seen)
    toast_call: Seen[ToastCall] = field(default_factory=Seen)
    retain_bytes: Optional[int] = WINDOW_RETENTION_BYTES
    since_trim: int = 0

    def __post_init__(self) -> None:
        self.cursor = max(self.cursor, self.coverage_start)
        self.machine.whole = self.coverage_start == 0
        self.starts.coverage_start = self.coverage_start
        for extreme in self.extremes():
            extreme.coverage_start = self.coverage_start

    def extremes(self) -> Tuple[SuffixExtreme, ...]:
        return (self.newest_append, self.newest_assistant, self.newest_prompt, self.newest_enqueue, self.newest_reply,
                self.newest_local_command, self.earliest_main)

    @property
    def bounded(self) -> bool:
        return self.retain_bytes is not None

    @property
    def whole(self) -> bool:
        return self.coverage_start == 0

    @property
    def boundary(self) -> Optional[TurnSnap]:
        return self.machine.boundary

    last_turn_end = boundary

    @property
    def mcp_events(self) -> Tuple[McpEvent, ...]:
        return self.mcp_log.merged(0)

    def window_view(self, bound: int) -> WindowView:
        return self.turn_log.window_view(bound, self.coverage_start, self.machine)


def _apply_events(state: ConvState, events: Sequence[TimelineEvent], start: int) -> None:
    for event in events:
        if event.thread == "side":
            continue
        if event.kind is Kind.TURN_END:
            state.open_turn = None
        elif event.turn is not None and event.kind is not Kind.QUEUE:
            state.open_turn = event.turn
        if event.kind is Kind.REPLY:
            state.newest_reply.observe(parse_timestamp(event.t), start)
        elif event.kind is Kind.QUEUE:
            _apply_queue(state, event)


def _apply_queue(state: ConvState, event: TimelineEvent) -> None:
    data, queued = event.data, state.queued
    op = data.get("op")
    if op == OP_ENQUEUE:
        queued.append(QueuedMessage(event.pos.offset, bool(data.get("plain")), data.get("chars"), data.get("command_uuid")))
        del queued[:-MAX_QUEUED]
    elif op == OP_DEQUEUE and queued:
        queued.pop(0)
    elif op == OP_REMOVE:
        for index, item in enumerate(queued):
            if item.chars == data.get("chars") and item.plain == bool(data.get("plain")):
                del queued[index]
                break
    elif op == OP_POP_ALL:
        queued.clear()


def _last_call(record: Mapping[str, Any]) -> Optional[BlockedCall]:
    if record.get("type") != "assistant":
        return None
    blocks = content_blocks(dict(record), "tool_use")
    return BlockedCall(blocks[-1].get("id"), blocks[-1].get("name")) if blocks else None


def _note_record(state: ConvState, record: Mapping[str, Any], start: int, at: Optional[datetime]) -> None:
    kind = record.get("type")
    if kind not in BOOKKEEPING_RECORD_TYPES:
        state.blocked.set(_last_call(record), start)
    if record.get("isSidechain") is not True:
        if isinstance(record.get("uuid"), str):
            state.leaf_uuid = record["uuid"]
        state.earliest_main.observe(at, start)
    state.newest_append.observe(at, start)
    if kind in ("custom-title", "ai-title"):
        title = record.get("customTitle" if kind == "custom-title" else "aiTitle")
        if isinstance(title, str) and title and (kind == "custom-title" or state.title is None):
            state.title = title


def _newest_last(table: Dict[str, int], key: str, start: int, cap: int, bounded: bool) -> None:
    table.pop(key, None)
    table[key] = start
    while bounded and len(table) > cap:
        del table[next(iter(table))]


def _notify(state: ConvState, ids: Sequence[str], start: int) -> None:
    for task in ids:
        _newest_last(state.notified, task, start, MAX_NOTIFIED, state.bounded)


def _retire(state: ConvState, ids: Sequence[str], start: int, *, force: bool = False) -> None:
    _notify(state, ids, start)
    if ids or force:
        state.machine.retire()
        state.turn_log.add(start, OP_RETIRE)


def _fold_system(state: ConvState, record: Mapping[str, Any], at: Optional[datetime], start: int) -> None:
    if record.get("subtype") == TURN_END_SUBTYPE:
        pending, present, workflows, notes = decode_turn_end_counts(dict(record))
        state.machine.turn_end(TurnSnap(at, TURN_END_DURATION, pending, present, workflows), notes)
        state.turn_log.reset(start)
        if pending == 0 and workflows == 0:
            for key in [k for k, launch in state.launches.items() if launch.kind in TURN_END_COUNTED_KINDS]:
                del state.launches[key]
    elif is_local_command(dict(record)):
        state.newest_local_command.observe(at, start)


def _fold_assistant(state: ConvState, record: Dict[str, Any], at: Optional[datetime], start: int) -> None:
    if is_resume_placeholder(record):
        return
    state.newest_assistant.observe(at, start)
    if record.get("isSidechain") is not True:
        state.usage_limit_hit.set(usage_limit_from_record(record), start)
    for block in content_blocks(record, "tool_use"):
        call_id = block.get("id")
        if isinstance(call_id, str) and call_id:
            state.machine.call(call_id)
            state.turn_log.add(start, OP_CALL, call_id)


def _fold_toast(state: ConvState, record: Dict[str, Any], start: int) -> None:
    if record.get("type") != "assistant" or record.get("isSidechain"):
        return
    piece = extract_toast_facts([record])
    if piece.last_text:
        state.toast_text.set(piece.last_text, start)
    calls = content_blocks(record, "tool_use")
    if calls:
        state.toast_call.set(ToastCall(calls[-1].get("id"), piece.pending_tool, piece.pending_target), start)


def _fold_queue_operation(state: ConvState, record: Mapping[str, Any], at: Optional[datetime], start: int) -> None:
    content = record.get("content")
    if record.get("operation") == ENQUEUE_OPERATION and isinstance(content, str) and content.lstrip().startswith(
        TASK_NOTIFICATION_MARKER
    ):
        state.newest_enqueue.observe(at, start)
        _retire(state, retired_ids(content), start)


def _fold_attachment(state: ConvState, record: Mapping[str, Any], start: int) -> None:
    attachment = record.get("attachment")
    if (
        isinstance(attachment, dict)
        and attachment.get("type") == QUEUED_COMMAND_ATTACHMENT
        and isinstance(attachment.get("prompt"), str)
    ):
        _retire(state, retired_ids(attachment["prompt"]), start)


def _fold_user(state: ConvState, record: Dict[str, Any], at: Optional[datetime], start: int) -> None:
    for block in content_blocks(record, "tool_result"):
        call_id = block.get("tool_use_id")
        if isinstance(call_id, str) and call_id:
            _newest_last(state.result_at, call_id, start, MAX_RESULT_IDS, state.bounded)
            if not record.get("isSidechain"):
                _newest_last(state.main_result_at, call_id, start, MAX_RESULT_IDS, state.bounded)
            state.machine.result(call_id)
            state.turn_log.add(start, OP_RESULT, call_id)
    if is_task_notification(record):
        _retire(state, retired_ids(record_text(record)), start)
        return
    stopped = stopped_task_id(record)
    if stopped is not None:
        _retire(state, [stopped], start, force=True)
        return
    launch = async_launch(record)
    if launch is not None:
        state.launches[launch.key] = LaunchRec(launch.key, launch.kind, launch.task_id, launch.tool_use_id, start, at)
        return
    _fold_boundary(state, record, at, start)


def _fold_boundary(state: ConvState, record: Dict[str, Any], at: Optional[datetime], start: int) -> None:
    typed = is_real_user_prompt(record)
    if is_interrupt(record):
        state.machine.interrupt(at)
        state.turn_log.add(start, OP_INTERRUPT, at)
    elif is_local_command(record):
        state.newest_local_command.observe(at, start)
    elif typed:
        state.prompt_seen.set(True, start)
        state.machine.prompt()
        state.turn_log.add(start, OP_PROMPT)
    if typed:
        state.newest_prompt.observe(at, start)


def _fold_mcp(state: ConvState, record: Mapping[str, Any], start: int) -> None:
    for event, origin in scan_record_located(record, state.mcp_open_calls, state.mcp_origins, start):
        state.mcp_log.add(start, origin, event)
    if state.retain_bytes is not None:
        state.mcp_log.trim(state.cursor, state.retain_bytes)
    while state.bounded and len(state.mcp_open_calls) > MAX_OPEN_CALLS:
        oldest = next(iter(state.mcp_open_calls))
        del state.mcp_open_calls[oldest]
        state.mcp_origins.pop(oldest, None)


def _retain(state: ConvState) -> None:
    state.since_trim += 1
    if state.retain_bytes is None or state.since_trim < TRIM_EVERY:
        return
    state.since_trim = 0
    horizon = state.cursor - state.retain_bytes
    trim_all(horizon, state.extremes(), state.starts)
    state.turn_log.trim(horizon)
    state.launches = {key: launch for key, launch in state.launches.items() if launch.offset >= horizon}
    state.result_at = {call_id: at for call_id, at in state.result_at.items() if at >= horizon}
    state.main_result_at = {call_id: at for call_id, at in state.main_result_at.items() if at >= horizon}
    state.notified = {task: at for task, at in state.notified.items() if at >= horizon}


def fold_record(state: ConvState, record: Any, events: Sequence[TimelineEvent], end_offset: int) -> None:
    start, state.cursor = state.cursor, end_offset
    state.starts.add(start)
    _apply_events(state, events, start)
    if isinstance(record, dict):
        at = parse_timestamp(record.get("timestamp"))
        state.shape.check(record, start)
        _note_record(state, record, start, at)
        _fold_mcp(state, record, start)
        kind = record.get("type")
        if kind == "system":
            _fold_system(state, record, at, start)
        elif kind == "assistant":
            _fold_assistant(state, record, at, start)
            _fold_toast(state, record, start)
        elif kind == "queue-operation":
            _fold_queue_operation(state, record, at, start)
        elif kind == "attachment":
            _fold_attachment(state, record, start)
        elif kind == "user":
            _fold_user(state, record, at, start)
    _retain(state)
