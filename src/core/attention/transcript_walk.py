from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from src.core.attention.transcript_records import (
    ENQUEUE_OPERATION,
    QUEUED_COMMAND_ATTACHMENT,
    TASK_NOTIFICATION_MARKER,
    TURN_END_DURATION,
    TURN_END_INTERRUPT,
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
    Launch,
    async_launch,
    content_blocks,
    decode_turn_end_counts,
    stopped_task_id,
)
from src.core.attention.usage_limit import UsageLimit, usage_limit_from_record
from src.core.session_status_seed_records import parse_timestamp

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


def _later(left: Optional[datetime], right: Optional[datetime]) -> Optional[datetime]:
    if left is None:
        return right
    if right is None:
        return left
    return right if right > left else left


@dataclass
class WindowWalk:

    window_is_whole_file: bool = False
    turn_end: Optional[Dict[str, Any]] = None
    pending: Optional[int] = None
    pending_present: bool = False
    workflows: Optional[int] = None
    notes: List[str] = field(default_factory=list)
    newest_append_at: Optional[datetime] = None
    newest_assistant_at: Optional[datetime] = None
    newest_user_prompt_at: Optional[datetime] = None
    newest_enqueue_at: Optional[datetime] = None
    launches: Dict[str, Launch] = field(default_factory=dict)
    launch_at: Dict[str, Optional[datetime]] = field(default_factory=dict)
    notified: Set[str] = field(default_factory=set)
    answered_tool_use_ids: Set[str] = field(default_factory=set)
    last_meaningful: Optional[Dict[str, Any]] = None
    turn_end_kind: Optional[str] = None
    before_interrupt: Optional[tuple] = None
    turn_tool_ids: Set[str] = field(default_factory=set)
    model_prompt_seen: bool = False
    newest_local_command_at: Optional[datetime] = None
    retired_since_turn_end: bool = False
    boundary_outside_window: bool = False
    limit_hit: Optional[UsageLimit] = None

    def feed(self, record: Any) -> None:
        if not isinstance(record, dict):
            return
        if record.get("type") not in BOOKKEEPING_RECORD_TYPES:
            self.last_meaningful = record
        at = parse_timestamp(record.get("timestamp"))
        self.newest_append_at = _later(self.newest_append_at, at)
        kind = record.get("type")
        if kind == "system":
            self._system(record, at)
        elif kind == "assistant":
            self._assistant(record, at)
        elif kind == "queue-operation":
            self._queue_operation(record, at)
        elif kind == "attachment":
            self._attachment(record)
        elif kind == "user":
            self._user(record, at)

    def _system(self, record: Dict[str, Any], at: Optional[datetime]) -> None:
        if record.get("subtype") == TURN_END_SUBTYPE:
            self.turn_end = record
            self.turn_end_kind = TURN_END_DURATION
            self.before_interrupt = None
            self.turn_tool_ids = set()
            self.retired_since_turn_end = False
            self.boundary_outside_window = False
            self.pending, self.pending_present, self.workflows, self.notes = (
                decode_turn_end_counts(record)
            )
            if self.pending == 0 and self.workflows == 0:
                self.launches = {
                    key: launch
                    for key, launch in self.launches.items()
                    if launch.kind not in TURN_END_COUNTED_KINDS
                }
        elif is_local_command(record):
            self.newest_local_command_at = _later(self.newest_local_command_at, at)

    def _assistant(self, record: Dict[str, Any], at: Optional[datetime]) -> None:
        if is_resume_placeholder(record):
            return
        self.newest_assistant_at = _later(self.newest_assistant_at, at)
        if record.get("isSidechain") is not True:
            self.limit_hit = usage_limit_from_record(record)
        for block in content_blocks(record, "tool_use"):
            if isinstance(block.get("id"), str) and block.get("id"):
                self.turn_tool_ids.add(block["id"])

    def _queue_operation(self, record: Dict[str, Any], at: Optional[datetime]) -> None:
        if record.get("operation") == ENQUEUE_OPERATION:
            content = record.get("content")
            if isinstance(content, str) and content.lstrip().startswith(
                TASK_NOTIFICATION_MARKER
            ):
                self.newest_enqueue_at = _later(self.newest_enqueue_at, at)
                retired = retired_ids(content)
                self.notified.update(retired)
                self.retired_since_turn_end = self.retired_since_turn_end or bool(retired)

    def _attachment(self, record: Dict[str, Any]) -> None:
        attachment = record.get("attachment")
        if (
            isinstance(attachment, dict)
            and attachment.get("type") == QUEUED_COMMAND_ATTACHMENT
            and isinstance(attachment.get("prompt"), str)
        ):
            retired = retired_ids(attachment["prompt"])
            self.notified.update(retired)
            self.retired_since_turn_end = self.retired_since_turn_end or bool(retired)

    def _user(self, record: Dict[str, Any], at: Optional[datetime]) -> None:
        for block in content_blocks(record, "tool_result"):
            candidate = block.get("tool_use_id")
            if isinstance(candidate, str) and candidate:
                self.answered_tool_use_ids.add(candidate)

        if is_task_notification(record):
            retired = retired_ids(record_text(record))
            self.notified.update(retired)
            self.retired_since_turn_end = self.retired_since_turn_end or bool(retired)
            return

        stopped = stopped_task_id(record)
        if stopped is not None:
            self.notified.add(stopped)
            self.retired_since_turn_end = True
            return

        launch = async_launch(record)
        if launch is not None:
            self.launches[launch.key] = launch
            self.launch_at[launch.key] = at
            return

        self._user_turn_boundary(record, at)

    def _user_turn_boundary(self, record: Dict[str, Any], at: Optional[datetime]) -> None:
        if is_interrupt(record):
            if self.turn_tool_ids <= self.answered_tool_use_ids:
                self.before_interrupt = (
                    self.turn_end, self.turn_end_kind, self.pending, self.pending_present, self.workflows
                )
                if self.turn_end is None:
                    if self.window_is_whole_file:
                        self.pending, self.workflows = 0, 0
                    else:
                        self.pending, self.workflows = None, None
                        self.boundary_outside_window = True
                elif self.retired_since_turn_end:
                    if self.pending:
                        self.pending = None
                    if self.workflows:
                        self.workflows = None
                self.turn_end = record
                self.turn_end_kind = TURN_END_INTERRUPT
                self.pending_present = False
                self.turn_tool_ids = set()
        elif is_local_command(record):
            self.newest_local_command_at = _later(self.newest_local_command_at, at)
        elif is_real_user_prompt(record):
            self.model_prompt_seen = True
            if self.before_interrupt is not None:
                self.turn_end, self.turn_end_kind, self.pending, self.pending_present, self.workflows = (
                    self.before_interrupt
                )
                self.before_interrupt = None
                self.boundary_outside_window = False

        if is_real_user_prompt(record):
            self.newest_user_prompt_at = _later(self.newest_user_prompt_at, at)
