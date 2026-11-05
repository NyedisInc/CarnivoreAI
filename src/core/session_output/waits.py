
from __future__ import annotations

import asyncio
import contextlib
import math
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Set, Tuple

from src.core.session_output import cursor as pipe_cursor
from src.core.session_output.tap import TAP, OutputTap

MAX_TIMEOUT_SECONDS = 50.0
MAX_PER_CALLER = 4
MAX_PER_ENGINE = 64
BACKSTOP_SECONDS = 5.0
MAX_MIN_QUIET_SECONDS = 10.0
MAX_TEXT_CHARS = 200
MAX_TAIL_LINES = 40
MAX_TAIL_BYTES = 8 * 1024
CARRY_BYTES = 4 * 1024
MIN_READ_INTERVAL_SECONDS = 0.5

STATE_SETS: Dict[str, frozenset] = {
    "idle": frozenset({"idle", "finished_unread"}),
    "blocked": frozenset({"question"}),
    "waiting": frozenset({"notice"}),
    "exited": frozenset({"dead"}),
}

MATCHED = "matched"
STILL_WAITING = "still_waiting"
CURSOR_RESET = "cursor_reset"
SESSION_GONE = "session_gone"


class WaitLimitError(Exception):

    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(frozen=True)
class WaitSpec:

    states: Tuple[str, ...] = ()
    text: Optional[str] = None
    timeout: float = MAX_TIMEOUT_SECONDS
    min_quiet: float = 0.0

    def display_states(self) -> frozenset:
        return frozenset().union(*(STATE_SETS[s] for s in self.states)) if self.states else frozenset()


@dataclass
class PipeSource:

    basis: Callable[[], Tuple[Path, float]]


@dataclass
class WaitOutcome:

    status: str
    matched: Optional[str]
    state: Optional[str]
    cursor: Optional[str]
    tail: Optional[str] = None
    elapsed_s: float = 0.0


@dataclass(eq=False)
class Waiter:

    status: Optional[str]
    changed_at: float = field(default_factory=time.monotonic)
    event: asyncio.Event = field(default_factory=asyncio.Event)

    def on_status(self, display: Optional[str]) -> None:
        if display != self.status:
            self.status, self.changed_at = display, time.monotonic()
        self.event.set()

    def on_chunk(self, _session_id: str, _data: bytes) -> None:
        self.event.set()


class WaitRegistry:

    def __init__(self, tap: OutputTap = TAP) -> None:
        self._tap = tap
        self._deadlines: Dict[str, List[float]] = {}
        self._waiters: Dict[str, Set[Waiter]] = {}

    @property
    def open_count(self) -> int:
        return sum(len(v) for v in self._deadlines.values())

    def caller_count(self, caller_key: str) -> int:
        return len(self._deadlines.get(caller_key, ()))

    @contextlib.contextmanager
    def slot(self, caller_key: str, timeout: float) -> Iterator[None]:
        now = time.monotonic()
        mine = self._deadlines.get(caller_key, [])
        if len(mine) >= MAX_PER_CALLER:
            raise WaitLimitError(f"you already have {MAX_PER_CALLER} waits open", _retry_after(mine, now))
        if self.open_count >= MAX_PER_ENGINE:
            every = [d for v in self._deadlines.values() for d in v]
            raise WaitLimitError(f"this computer already has {MAX_PER_ENGINE} waits open", _retry_after(every, now))
        deadline = now + timeout
        self._deadlines.setdefault(caller_key, []).append(deadline)
        try:
            yield
        finally:
            held = self._deadlines.get(caller_key, [])
            if deadline in held:
                held.remove(deadline)
            if not held:
                self._deadlines.pop(caller_key, None)

    @contextlib.contextmanager
    def watch(self, session_id: str, waiter: Waiter, output: bool) -> Iterator[None]:
        self._waiters.setdefault(session_id, set()).add(waiter)
        if output:
            self._tap.add(waiter.on_chunk, session_id=session_id)
        try:
            yield
        finally:
            if output:
                self._tap.remove(waiter.on_chunk, session_id=session_id)
            bucket = self._waiters.get(session_id)
            if bucket is not None:
                bucket.discard(waiter)
                if not bucket:
                    del self._waiters[session_id]

    def on_status(self, session_id: Optional[str], display: Optional[str]) -> None:
        if not self._waiters or session_id is None:
            return
        for waiter in list(self._waiters.get(session_id, ())):
            waiter.on_status(display)


def _retry_after(deadlines: List[float], now: float) -> int:
    return max(1, math.ceil(min(deadlines) - now)) if deadlines else 1


def caller_key(caller: object) -> str:
    token = getattr(caller, "token_name", "") or ""
    return f"token:{token}" if token else f"pane:{getattr(caller, 'tmux_name', '')}:{getattr(caller, 'proxied_agent_id', 0)}"


def _match_tail(text: str, needle: str, clean: Callable[[str], str]) -> Optional[str]:
    text = clean(text)
    idx = text.find(needle)
    if idx < 0:
        return None
    end = text.find("\n", idx + len(needle))
    return _cap_tail(text[: end if end >= 0 else len(text)])


def _cap_tail(text: str) -> str:
    tail = "\n".join(text.split("\n")[-MAX_TAIL_LINES:])
    raw = tail.encode("utf-8")
    if len(raw) > MAX_TAIL_BYTES:
        tail = raw[-MAX_TAIL_BYTES:].decode("utf-8", errors="ignore")
    return tail


async def run_wait(
    *,
    registry: WaitRegistry,
    session_id: str,
    caller: str,
    spec: WaitSpec,
    initial_status: Optional[str],
    pipe: Optional[PipeSource],
    since: Optional[pipe_cursor.Cursor],
    is_gone: Callable[[], bool],
    decode: Callable[[bytes], str],
    clean: Callable[[str], str],
) -> WaitOutcome:
    timeout = min(max(spec.timeout, 0.0), MAX_TIMEOUT_SECONDS)
    started = time.monotonic()
    waiter = Waiter(initial_status)
    with registry.slot(caller, timeout), registry.watch(session_id, waiter, output=pipe is not None and spec.text is not None):
        state = _State(spec, pipe, since, decode, clean, waiter, is_gone, started + timeout)
        if pipe is not None and state.cursor is None:
            path, stamp = pipe.basis()
            state.cursor = await asyncio.to_thread(pipe_cursor.at_end, path, stamp)
        try:
            outcome = await asyncio.wait_for(state.loop(), timeout + 1.0)
        except asyncio.TimeoutError:
            outcome = state.answer(STILL_WAITING, None)
    outcome.elapsed_s = round(time.monotonic() - started, 2)
    return outcome


class _State:

    def __init__(self, spec: WaitSpec, pipe: Optional[PipeSource], since: Optional[pipe_cursor.Cursor],
                 decode: Callable[[bytes], str], clean: Callable[[str], str], waiter: Waiter,
                 is_gone: Callable[[], bool], deadline: float) -> None:
        self.spec, self.pipe, self.cursor = spec, pipe, since
        self.decode, self.clean, self.waiter, self.is_gone, self.deadline = decode, clean, waiter, is_gone, deadline
        self.wanted = spec.display_states()
        self.carry = b""
        self.last_read = 0.0

    def answer(self, status: str, matched: Optional[str], tail: Optional[str] = None) -> WaitOutcome:
        return WaitOutcome(status, matched, self.waiter.status, self.cursor.encode() if self.cursor else None, tail)

    async def loop(self) -> WaitOutcome:
        while True:
            self.waiter.event.clear()
            if self.is_gone():
                return self.answer(SESSION_GONE, None)
            if self.spec.text is not None and self.pipe is not None:
                found = await self._read_output()
                if found is not None:
                    return found
            now = time.monotonic()
            wake_at = self.deadline
            status = self.waiter.status
            if status in self.wanted:
                quiet_until = self.waiter.changed_at + self.spec.min_quiet
                if now >= quiet_until:
                    return self.answer(MATCHED, f"state:{_name_of(status)}", await self._state_tail())
                wake_at = min(wake_at, quiet_until)
            if now >= self.deadline:
                return self.answer(STILL_WAITING, None)
            try:
                await asyncio.wait_for(self.waiter.event.wait(), max(0.0, min(wake_at - now, BACKSTOP_SECONDS)))
            except asyncio.TimeoutError:
                pass

    async def _read_output(self) -> Optional[WaitOutcome]:
        gap = MIN_READ_INTERVAL_SECONDS - (time.monotonic() - self.last_read)
        if gap > 0:
            await asyncio.sleep(min(gap, max(0.0, self.deadline - time.monotonic())))
        while True:
            path, stamp = self.pipe.basis()
            result = await asyncio.to_thread(pipe_cursor.read_since, path, stamp, self.cursor)
            self.last_read = time.monotonic()
            self.cursor = result.next
            if result.reset:
                return self.answer(CURSOR_RESET, None)
            if not result.data:
                return None
            window = self.carry + result.data
            tail = _match_tail(self.decode(window), self.spec.text, self.clean)
            if tail is not None:
                return self.answer(MATCHED, "output", tail)
            self.carry = window[-CARRY_BYTES:]
            if not result.more or time.monotonic() >= self.deadline:
                return None
            await asyncio.sleep(0)

    async def _state_tail(self) -> Optional[str]:
        if self.pipe is None or self.cursor is None:
            return None
        path, stamp = self.pipe.basis()
        result = await asyncio.to_thread(pipe_cursor.read_tail, path, stamp, self.cursor)
        self.cursor = result.next
        return _cap_tail(self.clean(self.decode(result.data))) if result.data else None


def _name_of(display: Optional[str]) -> str:
    return next((name for name, members in STATE_SETS.items() if display in members), str(display))


REGISTRY = WaitRegistry()
