
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from src.core.timeline.model import (
    FAMILY_CLAUDE,
    Family,
    FILE_KEY_MAIN,
    THREAD_AGENT_PREFIX,
    THREAD_MAIN,
    THREAD_SIDE,
    Kind,
    Pos,
    TimelineEvent,
    is_iso_time,
)


@dataclass
class ToolRef:

    name: str
    call_id: Optional[str]


@dataclass
class ExtractContext:

    conv: str
    file_key: str = FILE_KEY_MAIN
    family: Family = FAMILY_CLAUDE
    turn: Optional[int] = None
    turn_ended: bool = False
    tools: Dict[str, ToolRef] = field(default_factory=dict)
    tasks: Dict[str, str] = field(default_factory=dict)
    last_t: Optional[str] = None
    compaction_id: Optional[str] = None
    fork_announced: bool = False
    closed_msg: Optional[str] = None
    closed_end: Optional[str] = None
    turn_has_end: bool = False

    @property
    def file_thread(self) -> str:
        return THREAD_MAIN if self.file_key == FILE_KEY_MAIN else f"{THREAD_AGENT_PREFIX}{self.file_key}"


class LineScope:

    def __init__(self, ctx: ExtractContext, record: Mapping[str, Any], pos: Pos) -> None:
        self.ctx = ctx
        self.record = record
        self.pos = pos
        self.events: List[TimelineEvent] = []
        self.thread = ctx.file_thread
        if self.thread == THREAD_MAIN and record.get("isSidechain") is True:
            self.thread = THREAD_SIDE
        stamp = record.get("timestamp", record.get("ts"))
        self.t: Optional[str] = stamp if is_iso_time(stamp) else ctx.last_t
        if is_iso_time(stamp):
            ctx.last_t = stamp

    @property
    def tracks_turns(self) -> bool:
        return self.thread != THREAD_SIDE

    def open_turn(self) -> None:
        if self.tracks_turns:
            ctx = self.ctx
            ctx.turn, ctx.turn_ended, ctx.turn_has_end, ctx.closed_msg, ctx.closed_end = self.pos.offset, False, False, None, None

    def reopen_turn(self) -> None:
        if self.tracks_turns:
            self.ctx.turn_ended = False

    def close_turn(self) -> bool:
        if not self.tracks_turns:
            return False
        already = self.ctx.turn_has_end
        self.ctx.turn_ended = self.ctx.turn_has_end = True
        self.ctx.closed_end = None
        return already

    def _turn_for(self, kind: Kind, msg: Optional[str]) -> Optional[int]:
        if not self.tracks_turns:
            return None
        if self.ctx.turn_ended and kind is not Kind.TURN_END and not (msg and msg == self.ctx.closed_msg):
            return None
        return self.ctx.turn

    def emit(self, kind: Kind, data: Optional[Dict[str, Any]] = None, *, parent: Optional[str] = None,
             msg: Optional[str] = None) -> TimelineEvent:
        event = TimelineEvent(
            pos=self.pos, n=len(self.events), t=self.t, family=self.ctx.family, thread=self.thread,
            turn=self._turn_for(kind, msg), parent=parent, msg=msg, kind=kind,
            data={key: value for key, value in (data or {}).items() if value is not None},
        )
        self.events.append(event)
        return event
