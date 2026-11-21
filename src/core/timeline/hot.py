
from __future__ import annotations

import json
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple, TypeVar

import structlog

from src.core.attention.transcript_facts import FACTS_WIDE_TAIL_BYTES, TranscriptFacts
from src.core.mcp_health import history as mcp_history
from src.core.pipeline import contract as pipeline_contract
from src.core.pipeline import reader as pipeline_reader
from src.core.timeline import agent_tail, gate, subscribe
from src.core.timeline.context import ExtractContext
from src.core.timeline.extract import extract_line
from src.core.timeline.facts_adapter import facts_from_state
from src.core.timeline.fold import ConvState, fold_record
from src.core.timeline.model import TimelineEvent
from src.core.timeline.pairs import PairBook
from src.core.transcript_manifest.tail import serial_of_record

logger = structlog.get_logger(__name__)

T = TypeVar("T")

STATUS_SOURCE_ENV, SOURCE_LEGACY, SOURCE_SHADOW, SOURCE_FOLD, DEFAULT_SOURCE = (
    gate.STATUS_SOURCE_ENV, gate.SOURCE_LEGACY, gate.SOURCE_SHADOW, gate.SOURCE_FOLD, gate.DEFAULT_SOURCE)
GATE_TTL_SECONDS: float = 5.0
MAX_STEP_BYTES: int = FACTS_WIDE_TAIL_BYTES
MAX_HOT_FILES: int = 128
HOT_IDLE_SECONDS: float = 30 * 60
_READ_ERRORS = (OSError, ValueError)


def status_source() -> str:
    return gate.status_source()


def _switch_on() -> bool:
    return gate.switch_on()


@dataclass
class _Gate:

    on: bool = False
    read_at: float = float("-inf")
    lock: threading.Lock = field(default_factory=threading.Lock)


_GATE = _Gate()


def shadow_enabled(*, clock: Callable[[], float] = time.monotonic) -> bool:
    now = clock()
    with _GATE.lock:
        if now - _GATE.read_at < GATE_TTL_SECONDS:
            return _GATE.on
    on = status_source() != SOURCE_LEGACY and _switch_on()
    with _GATE.lock:
        was, _GATE.on, _GATE.read_at = _GATE.on, on, now
    if was and not on:
        DRIVER.clear()
        PAIRS.clear()
        subscribe.drop_memory()
        logger.info("timeline_shadow_off")
    elif on and not was:
        logger.info("timeline_shadow_on", status_source=status_source())
    return on


def reset_gate() -> None:
    with _GATE.lock:
        _GATE.read_at = float("-inf")
        _GATE.on = False


@dataclass
class HotFile:

    inode: int
    state: ConvState
    ctx: ExtractContext
    last_start: Optional[int] = None
    last_serial: Optional[str] = None
    read_at: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


def _seed_start(path: str, size: int) -> int:
    nominal = max(0, size - FACTS_WIDE_TAIL_BYTES)
    if nominal == 0:
        return 0
    from src.core.claude_title_sync import align_to_record_start  # noqa: PLC0415

    with open(path, "rb") as handle:
        aligned = align_to_record_start(handle, nominal, max_scan=FACTS_WIDE_TAIL_BYTES)
        if aligned is not None:
            return aligned
        handle.seek(nominal)
        return nominal + len(handle.readline())


@dataclass
class FoldStep:

    from_offset: int
    from_serial: Optional[str]
    to_offset: int
    to_serial: Optional[str]
    events: List[TimelineEvent] = field(default_factory=list)


def fold_window(real: str, size: Optional[int] = None) -> Tuple[ConvState, Optional[str]]:
    size = os.stat(real).st_size if size is None else size
    conv = Path(real).stem
    start = _seed_start(real, size)
    hot = HotFile(0, ConvState(conv=conv, coverage_start=start), ExtractContext(conv=conv))
    HotDriver._fold_to(real, hot, size)
    return hot.state, hot.last_serial


class HotDriver:

    def __init__(self, limit: int = MAX_HOT_FILES) -> None:
        self._files: "OrderedDict[str, HotFile]" = OrderedDict()
        self._limit = limit
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._files.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._files)

    def _seed(self, path: str, real: str, inode: int, size: int) -> Tuple[HotFile, Optional[FoldStep]]:
        start = _seed_start(real, size)
        conv = Path(real).stem
        hot = HotFile(inode, ConvState(conv=conv, coverage_start=start), ExtractContext(conv=conv))
        history = mcp_history.entry_copy(path)
        if history is not None:
            hot.state.mcp_log.history = history
        return hot, self._fold_to(real, hot, size)

    @staticmethod
    def _fold_to(path: str, hot: HotFile, size: int) -> Optional[FoldStep]:
        state = hot.state
        if size <= state.cursor:
            return None
        with open(path, "rb") as handle:
            handle.seek(state.cursor)
            chunk = handle.read(size - state.cursor)
        offset = state.cursor
        step = FoldStep(offset, hot.last_serial, offset, hot.last_serial)
        collect = subscribe.listening()
        for raw in chunk.splitlines(keepends=True):
            if not raw.endswith(b"\n"):
                break
            body = raw[:-1]
            try:
                record = json.loads(body)
            except ValueError:
                record = None
            serial = serial_of_record(record, body)
            end = offset + len(raw)
            try:
                events = extract_line(hot.ctx, body, end, serial=serial)
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                logger.warning("timeline_hot_extract_failed", conv=state.conv, offset=offset, error=type(exc).__name__)
                events = []
            fold_record(state, record, events, end)
            hot.last_start, hot.last_serial = offset, serial
            if collect:
                step.events.extend(events)
            offset = end
        step.to_offset, step.to_serial = offset, hot.last_serial
        return step if offset > step.from_offset else None

    @staticmethod
    def _stepped(real: str, hot: HotFile, size: int) -> Tuple[bool, Optional[FoldStep], Optional[str]]:
        check = pipeline_reader.check_cursor(real, size, hot.state.cursor, hot.last_serial, hot.last_start)
        if check.reset is not None:
            return False, None, check.reset
        if size - hot.state.cursor > MAX_STEP_BYTES:
            return False, None, None
        return True, HotDriver._fold_to(real, hot, size), None

    @staticmethod
    def _announce(hot: HotFile, step: Optional[FoldStep], facts: TranscriptFacts, reset: Optional[str]) -> None:
        if step is not None or reset is not None:
            step = step or FoldStep(hot.state.cursor, hot.last_serial, hot.state.cursor, hot.last_serial)
            subscribe.offer_step(hot.state.conv, step, hot.state, facts, reset)

    def with_state(self, real: str, read: Callable[[ConvState, Optional[str]], T]) -> Optional[T]:
        with self._lock:
            hot = self._files.get(real)
        if hot is None:
            return None
        with hot.lock:
            return read(hot.state, hot.last_serial)

    def _keep(self, real: str, hot: HotFile) -> None:
        with self._lock:
            self._files[real] = hot
            self._files.move_to_end(real)
            while len(self._files) > self._limit:
                self._files.popitem(last=False)

    def _lookup(self, real: str, now: float) -> Optional[HotFile]:
        with self._lock:
            for stale in [key for key, kept in self._files.items() if now - kept.read_at > HOT_IDLE_SECONDS]:
                del self._files[stale]
            hot = self._files.get(real)
            if hot is not None:
                hot.read_at = now
                self._files.move_to_end(real)
            return hot

    def facts_at(self, path: str, size: int, *, now: Optional[datetime] = None,
                 clock: Callable[[], float] = time.monotonic) -> Optional[TranscriptFacts]:
        real = os.path.realpath(path)
        stat = os.stat(real)
        hot = self._lookup(real, clock())
        reset: Optional[str] = None
        if hot is not None and hot.inode == stat.st_ino:
            with hot.lock:
                if size < hot.state.cursor <= stat.st_size:
                    return None
                stepped, step, reset = self._stepped(real, hot, size)
                if stepped:
                    facts = facts_from_state(hot.state, now=now, size=size)
                    self._announce(hot, step, facts, None)
                    return facts
        elif hot is not None:
            reset = pipeline_contract.EV_FILE_REWRITTEN
        hot, step = self._seed(path, real, stat.st_ino, size)
        hot.read_at = clock()
        with hot.lock:
            facts = facts_from_state(hot.state, now=now, size=size)
            self._announce(hot, step, facts, reset)
        self._keep(real, hot)
        return facts


DRIVER = HotDriver()
PAIRS = PairBook()


def _shadow(path: str, key: Tuple[int, int], legacy: TranscriptFacts, now: Optional[datetime]) -> None:
    if not shadow_enabled():
        return
    stat = os.stat(path)
    after = (stat.st_mtime_ns, stat.st_size)
    fold = DRIVER.facts_at(path, after[1], now=now)
    agent_tail.wake(path, Path(path).stem)
    if fold is None or after != key:
        PAIRS.mark_raced(legacy, after[1])
    else:
        PAIRS.file(legacy, fold, after[1])


def shadow_read(path: str, key: Tuple[int, int], legacy: TranscriptFacts, *, now: Optional[datetime] = None) -> None:
    try:
        _shadow(path, key, legacy, now)
    except _READ_ERRORS as exc:
        logger.debug("timeline_hot_unreadable", path_tail=os.path.basename(path), error=type(exc).__name__)
    except Exception as exc:  # noqa: BLE001
        logger.error("timeline_hot_bug", path_tail=os.path.basename(path), error=type(exc).__name__, exc_info=True)
