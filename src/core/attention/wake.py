
from __future__ import annotations

import asyncio
import os
import time
from typing import Callable, Dict, Iterable, Mapping, Optional, Set

import structlog

from src.core import fs_event_index
from src.core.attention.fs_trigger import FsTrigger
from src.core.pipe_wakeup import PipeWaiter

logger = structlog.get_logger()

WAKE_POKE = "poke"
WAKE_FILES = "files"
WAKE_APPEND = "append"
WAKE_TICK = "tick"


class WakeSources:

    def __init__(self, registry_directory: str, *, watch_files: bool) -> None:
        self.registry_directory = registry_directory
        self._watch_files = watch_files
        self.poked: Set[str] = set()
        self._poke_event = asyncio.Event()
        self._dir_fd: Optional[int] = None
        self.waiter: Optional[PipeWaiter] = None
        self.trigger: Optional[FsTrigger] = None
        self._index: Optional[fs_event_index.FsEventIndex] = None
        self._unsubscribe: Optional[Callable[[], None]] = None
        self._indexed: Dict[str, Set[str]] = {}
        self._files: Set[str] = set()
        self._files_event = asyncio.Event()
        self.next_full_at = 0.0
        self._later: Dict[str, asyncio.TimerHandle] = {}


    @property
    def early_wake(self) -> bool:
        return bool(self.waiter is not None and self.waiter.watching)

    @property
    def file_trigger(self) -> bool:
        return bool(self.trigger is not None and self.trigger.active)

    def full_due(self) -> bool:
        return time.monotonic() >= self.next_full_at or not self._files

    def full_pass_started(self) -> None:
        self.poked.clear()
        self._poke_event.clear()
        self._files.clear()
        self._files_event.clear()

    def full_pass_done(self, tick_seconds: float) -> None:
        self.next_full_at = time.monotonic() + tick_seconds

    def take_files(self) -> Set[str]:
        pending, self._files = self._files, set()
        self._files_event.clear()
        return pending


    def poke(self, key: str) -> None:
        self.poked.add(key)
        self._poke_event.set()

    def files_changed(self, session_ids: Set[str]) -> None:
        self._files |= session_ids
        self._files_event.set()

    def wake_later(self, session_id: str, delay: float) -> None:
        if not self.file_trigger:
            return
        previous = self._later.pop(session_id, None)
        if previous is not None:
            previous.cancel()
        loop = asyncio.get_running_loop()

        def fire() -> None:
            self._later.pop(session_id, None)
            self.files_changed({session_id})

        self._later[session_id] = loop.call_later(max(0.0, delay), fire)

    def rearm(self, desired: Mapping[str, Iterable[str]]) -> None:
        if self.trigger is None:
            return
        index = self._index
        if index is not None and index.watching:
            kqueue = {p: ids for p, ids in desired.items() if not index.serves(p)}
            self._indexed = {p: set(ids) for p, ids in desired.items() if index.serves(p)}
        else:
            kqueue, self._indexed = dict(desired), {}
        self.trigger.rearm(kqueue)

    def index_changed(self, paths: Set[str]) -> None:
        woken: Set[str] = set()
        if fs_event_index.RESYNC in paths:
            for ids in self._indexed.values():
                woken |= ids
        for path in paths:
            woken |= self._indexed.get(path, set())
            woken |= self._indexed.get(os.path.dirname(path), set())
        if woken:
            self.files_changed(woken)

    def open(self) -> None:
        try:
            self._dir_fd = os.open(self.registry_directory, os.O_RDONLY)
        except OSError as exc:
            logger.debug("attention_watch_directory_unavailable",
                         directory=self.registry_directory, error=str(exc))
            self._dir_fd = None
        else:
            self.waiter = PipeWaiter(self._dir_fd)
        if self._watch_files:
            self.trigger = FsTrigger(self.files_changed)
            self.trigger.start()
            self._index = fs_event_index.start()
            self._unsubscribe = self._index.subscribe(self.index_changed)

    def close(self) -> None:
        for handle in self._later.values():
            handle.cancel()
        self._later.clear()
        waiter, fd, trigger = self.waiter, self._dir_fd, self.trigger
        self.waiter = self.trigger = None
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        self._index, self._indexed = None, {}
        self._dir_fd = None
        if trigger is not None:
            trigger.close()
        if waiter is not None:
            waiter.close()
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


    async def wait(self, tick_seconds: float) -> str:
        if self._poke_event.is_set():
            self.next_full_at = 0.0
            return WAKE_POKE
        if self._files_event.is_set():
            return WAKE_FILES
        timeout = (max(0.0, self.next_full_at - time.monotonic())
                   if self.next_full_at else tick_seconds)
        poke_task = asyncio.ensure_future(self._poke_event.wait())
        files_task = asyncio.ensure_future(self._files_event.wait())
        backstop = asyncio.ensure_future(self.backstop(timeout))
        try:
            done, _pending = await asyncio.wait(
                {poke_task, files_task, backstop}, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for task in (poke_task, files_task, backstop):
                if not task.done():
                    task.cancel()
        if poke_task in done:
            self.next_full_at = 0.0
            return WAKE_POKE
        if backstop in done and backstop.result():
            self.next_full_at = 0.0
            return WAKE_APPEND
        if files_task in done:
            return WAKE_FILES
        return WAKE_TICK

    async def backstop(self, seconds: float) -> bool:
        waiter = self.waiter
        if waiter is None:
            await asyncio.sleep(seconds)
            return False
        return await waiter.wait(seconds)
