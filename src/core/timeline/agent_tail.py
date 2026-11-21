
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog

from src.core.pipeline import contract as pipeline_contract
from src.core.timeline import cursor as cursors
from src.core.timeline import files, gate, reading
from src.core.timeline.context import ExtractContext
from src.core.timeline.model import FAMILY_CLAUDE, Family, TimelineEvent
from src.core.transcript_manifest.tail import read_last_line

log = structlog.get_logger(__name__)

MAX_STEP_BYTES: int = 4 * 1024 * 1024
MAX_PAGES_PER_POLL: int = 8
MAX_TAILS: int = 64
MAX_PENDING: int = 256
_READ_ERRORS = (OSError,)


@dataclass
class _AgentPos:

    inode: int
    size: int = 0
    end: int = 0
    serial: Optional[str] = None
    ctx: Optional[ExtractContext] = None


@dataclass
class _Tail:

    agents: Dict[str, _AgentPos] = field(default_factory=dict)
    polled: bool = False
    dropped: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


class AgentTails:

    worker_enabled: bool = True

    def __init__(self) -> None:
        self._tails: "OrderedDict[str, _Tail]" = OrderedDict()
        self._guard = threading.Lock()
        self._pending: Dict[str, str] = {}
        self._wakeup = threading.Condition()
        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def clear(self) -> None:
        with self._wakeup:
            self._pending.clear()
            self._stop.set()
            self._stop = threading.Event()
            self._worker = None
            self._wakeup.notify_all()
        with self._guard:
            for tail in self._tails.values():
                tail.dropped = True
            self._tails.clear()

    def enqueue(self, main_real: str, conv: str) -> None:
        with self._wakeup:
            self._pending.pop(main_real, None)
            self._pending[main_real] = conv
            while len(self._pending) > MAX_PENDING:
                self._pending.pop(next(iter(self._pending)))
            if self.worker_enabled and (self._worker is None or not self._worker.is_alive()):
                self._stop = threading.Event()
                self._worker = threading.Thread(target=self._run, args=(self._stop,), name="timeline-agent-tail", daemon=True)
                self._worker.start()
            self._wakeup.notify()

    def _take_pending(self) -> Dict[str, str]:
        with self._wakeup:
            taken = dict(self._pending)
            self._pending.clear()
            return taken

    def drain(self, stop: Optional[threading.Event] = None) -> int:
        stop = stop or self._stop
        moved = 0
        for main_real, conv in self._take_pending().items():
            if stop.is_set():
                break
            try:
                moved += self.poll(main_real, conv)
            except Exception as exc:  # noqa: BLE001
                log.error("timeline_agent_poll_failed", conv=conv, error=type(exc).__name__, exc_info=True)
        return moved

    def _run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            with self._wakeup:
                while not self._pending and not stop.is_set():
                    self._wakeup.wait()
            if stop.is_set():
                return
            self.drain(stop)

    def _tail_for(self, main_real: str) -> _Tail:
        with self._guard:
            tail = self._tails.get(main_real)
            if tail is None:
                tail = self._tails[main_real] = _Tail()
            self._tails.move_to_end(main_real)
            while len(self._tails) > MAX_TAILS:
                self._tails.popitem(last=False)[1].dropped = True
            return tail

    def poll(self, main_real: str, conv: str, family: Family = FAMILY_CLAUDE) -> int:
        found = files.agent_files(main_real)
        tail = self._tail_for(main_real)
        moved, unfinished = 0, False
        with tail.lock:
            if tail.dropped:
                return 0
            first, tail.polled = not tail.polled, True
            for agent_id, real in found.items():
                if tail.dropped:
                    return moved
                try:
                    did, done = self._poll_file(tail.agents, first, conv, agent_id, real, family)
                    moved += did
                    unfinished = unfinished or not done
                except _READ_ERRORS as exc:
                    log.debug("timeline_agent_tail_unreadable", conv=conv, agent=agent_id, error=type(exc).__name__)
            unfinished = unfinished and not tail.dropped
        if unfinished:
            self.enqueue(main_real, conv)
        return moved

    @staticmethod
    def _baseline(real: str, inode: int, size: int) -> _AgentPos:
        last = read_last_line(Path(real), size)
        return _AgentPos(inode, size, last.end or 0, last.serial if last.end else None)

    def _poll_file(self, known: Dict[str, _AgentPos], first: bool, conv: str, agent_id: str, real: str, family: Family) -> Tuple[int, bool]:
        stat = os.stat(real)
        pos = known.get(agent_id)
        if pos is None:
            if first:
                known[agent_id] = self._baseline(real, stat.st_ino, stat.st_size)
                return 0, True
            pos = known[agent_id] = _AgentPos(stat.st_ino)
        if pos.inode == stat.st_ino and pos.size == stat.st_size:
            return 0, True
        return 1, self._step(pos, conv, agent_id, real, family, stat)

    @staticmethod
    def _advance(pos: _AgentPos, conv: str, agent_id: str, real: str, family: Family, stat: os.stat_result) -> Tuple[List[TimelineEvent], bool]:
        from src.core.timeline import subscribe  # noqa: PLC0415

        if not subscribe.listening() or stat.st_size - pos.end > MAX_STEP_BYTES:
            last = read_last_line(Path(real), stat.st_size)
            pos.end, pos.serial, pos.ctx = last.end or 0, last.serial if last.end else None, None
            return [], True
        events: List[TimelineEvent] = []
        pos.ctx = pos.ctx or reading.warm_context(conv, agent_id, family, real, pos.end)
        for _ in range(MAX_PAGES_PER_POLL):
            page = reading.read_from(real, conv, agent_id, family, pos.end, pos.serial, size=stat.st_size, ctx=pos.ctx,
                                     max_bytes=MAX_STEP_BYTES, remember=False)
            events.extend(page.events)
            moved = page.end > pos.end
            pos.end, pos.serial = page.end, page.last_serial
            if page.at_end or page.end >= stat.st_size or not moved:
                return events, True
        return events, False

    @staticmethod
    def _step(pos: _AgentPos, conv: str, agent_id: str, real: str, family: Family, stat: os.stat_result) -> bool:
        from src.core.timeline import subscribe  # noqa: PLC0415

        before = subscribe.PosRef(pos.end, pos.serial)
        reset = None
        if pos.inode != stat.st_ino:
            reset = pipeline_contract.EV_FILE_REWRITTEN
        elif pos.end > 0:
            reset = cursors.check(real, cursors.Cursor(conv, agent_id, pos.end, pos.serial or ""), size=stat.st_size)
        if reset is not None:
            pos.inode, pos.end, pos.serial, pos.ctx = stat.st_ino, 0, None, None
        events, done = AgentTails._advance(pos, conv, agent_id, real, family, stat)
        pos.size = stat.st_size if done else -1
        subscribe.offer_agent(conv, agent_id, before, subscribe.PosRef(pos.end, pos.serial), events, reset)
        return done


TAILS = AgentTails()


MAX_STATE_AGENT_FILES = 32


def file_positions(main_real: str, limit: int = MAX_STATE_AGENT_FILES) -> Tuple[Dict[str, List], int]:
    stamped = []
    for agent_id, real in files.agent_files(main_real).items():
        try:
            info = os.stat(real)
        except OSError as exc:
            log.debug("timeline_agent_position_unreadable", agent=agent_id, error=type(exc).__name__)
            continue
        stamped.append((info.st_mtime, agent_id, real, info.st_size))
    stamped.sort(reverse=True)
    out: Dict[str, List] = {}
    for _mtime, agent_id, real, size in stamped[:max(0, limit)]:
        try:
            last = read_last_line(Path(real), size)
        except OSError as exc:
            log.debug("timeline_agent_position_unreadable", agent=agent_id, error=type(exc).__name__)
            continue
        out[agent_id] = [last.end or 0, last.serial if last.end else None]
    return out, len(stamped)


def wake(main_path: str, conv: str) -> None:
    try:
        if gate.hook_on():
            TAILS.enqueue(os.path.realpath(main_path), conv)
    except Exception as exc:  # noqa: BLE001
        log.error("timeline_agent_wake_failed", conv=conv, error=type(exc).__name__, exc_info=True)
