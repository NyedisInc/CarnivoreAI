
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, NamedTuple, Optional, Sequence, Set, Tuple

from src.core.attention.transcript_records import TURN_END_DURATION, TURN_END_INTERRUPT

OP_CALL, OP_RESULT, OP_RETIRE, OP_INTERRUPT, OP_PROMPT = "call", "result", "retire", "interrupt", "prompt"


@dataclass(frozen=True)
class TurnSnap:

    at: Optional[datetime]
    kind: str
    pending: Optional[int]
    pending_present: bool
    workflows: Optional[int]


class Op(NamedTuple):

    offset: int
    code: str
    arg: Optional[object] = None


class WindowView(NamedTuple):

    kind: Optional[str]
    outside: bool


@dataclass
class TurnMachine:

    whole: bool = True
    boundary: Optional[TurnSnap] = None
    before_interrupt: Optional[Tuple[Optional[TurnSnap]]] = None
    unanswered: Set[str] = field(default_factory=set)
    retired_since: bool = False
    outside: bool = False
    notes: List[str] = field(default_factory=list)

    def turn_end(self, snap: TurnSnap, notes: Sequence[str]) -> None:
        self.boundary, self.before_interrupt = snap, None
        self.unanswered = set()
        self.retired_since = self.outside = False
        self.notes = list(notes)

    def call(self, call_id: str) -> None:
        self.unanswered.add(call_id)

    def result(self, call_id: str) -> None:
        self.unanswered.discard(call_id)

    def retire(self) -> None:
        self.retired_since = True

    def interrupt(self, at: Optional[datetime]) -> None:
        if self.unanswered:
            return
        prev = self.boundary
        self.before_interrupt = (prev,)
        if prev is None:
            pending, workflows = (0, 0) if self.whole else (None, None)
            self.outside = self.outside or not self.whole
        else:
            pending, workflows = prev.pending, prev.workflows
            if self.retired_since:
                pending = None if pending else pending
                workflows = None if workflows else workflows
        self.boundary = TurnSnap(at, TURN_END_INTERRUPT, pending, False, workflows)
        self.unanswered = set()

    def prompt(self) -> None:
        if self.before_interrupt is not None:
            self.boundary = self.before_interrupt[0]
            self.before_interrupt = None
            self.outside = False

    def apply(self, op: Op) -> None:
        if op.code == OP_CALL:
            self.call(str(op.arg))
        elif op.code == OP_RESULT:
            self.result(str(op.arg))
        elif op.code == OP_RETIRE:
            self.retire()
        elif op.code == OP_INTERRUPT:
            self.interrupt(op.arg if isinstance(op.arg, datetime) else None)
        elif op.code == OP_PROMPT:
            self.prompt()


@dataclass
class TurnLog:

    ops: List[Op] = field(default_factory=list)
    last_end: int = -1

    def add(self, offset: int, code: str, arg: Optional[object] = None) -> None:
        self.ops.append(Op(offset, code, arg))

    def reset(self, offset: int) -> None:
        self.ops.clear()
        self.last_end = offset

    def trim(self, horizon: int) -> None:
        drop = bisect_left(self.ops, horizon, key=lambda op: op.offset)
        if drop:
            del self.ops[:drop]

    def window_view(self, bound: int, coverage_start: int, full: TurnMachine) -> WindowView:
        if bound <= coverage_start:
            return WindowView(full.boundary.kind if full.boundary else None, full.outside)
        if bound <= self.last_end:
            return WindowView(TURN_END_DURATION, False)
        fresh = TurnMachine(whole=False)
        for op in self.ops[bisect_left(self.ops, bound, key=lambda item: item.offset):]:
            fresh.apply(op)
        return WindowView(fresh.boundary.kind if fresh.boundary else None, fresh.outside)
