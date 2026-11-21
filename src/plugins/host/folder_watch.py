
from __future__ import annotations

import asyncio
import os
import select
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import structlog

from src.core.plugin_health.presence import GONE
from src.plugins.host import install_folder, prune_gone

logger = structlog.get_logger()

KQUEUE_AVAILABLE: bool = hasattr(select, "kqueue")
SETTLE_S = 2.0
MAX_EVENTS = 64
_OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_EVTONLY", 0)


def _vnode_fflags() -> int:
    if not KQUEUE_AVAILABLE:
        return 0
    return select.KQ_NOTE_DELETE | select.KQ_NOTE_WRITE | select.KQ_NOTE_RENAME | select.KQ_NOTE_LINK


class FolderWatch:

    def __init__(self, live: Any, settle: float = SETTLE_S) -> None:
        self._live, self._settle = live, settle
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._kq: Optional["select.kqueue"] = None
        self._fds: Dict[Path, int] = {}
        self._warned: Set[Path] = set()
        self._pending: Optional[asyncio.Task] = None
        self._aiming: Optional[asyncio.Task] = None
        self._aim_lock = asyncio.Lock()
        self._dirty = False
        self._unsupported_logged = False

    @property
    def watched(self) -> List[Path]:
        return sorted(self._fds)

    def start(self) -> None:
        if self._kq is not None:
            return
        if not KQUEUE_AVAILABLE:
            self._log_unsupported()
            return
        kq = None
        try:
            kq = select.kqueue()
            loop = asyncio.get_running_loop()
            loop.add_reader(kq.fileno(), self._on_readable)
        except (OSError, ValueError, NotImplementedError) as exc:
            logger.warning("plugin_folder_watch_unavailable", error_type=type(exc).__name__)
            if kq is not None:
                kq.close()
            return
        self._kq, self._loop = kq, loop
        self._aim(self._wanted())

    def refresh(self) -> None:
        if self._kq is not None and self._loop is not None:
            self._aiming = self._loop.create_task(self._reaim())

    async def _reaim(self) -> None:
        async with self._aim_lock:
            wanted = await asyncio.to_thread(self._wanted)
            if self._kq is not None:
                self._aim(wanted)

    async def stop(self) -> None:
        tasks = [t for t in (self._pending, self._aiming) if t is not None]
        self._pending = self._aiming = None
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        kq, self._kq = self._kq, None
        if kq is not None and self._loop is not None:
            self._loop.remove_reader(kq.fileno())
        for fd in self._fds.values():
            self._close(fd)
        self._fds.clear()
        if kq is not None:
            kq.close()

    def _wanted(self) -> Set[Path]:
        try:
            installed = prune_gone.installed(self._live)
        except prune_gone.PRUNE_ERRORS as exc:
            logger.warning("plugin_folder_watch_ledger_unreadable", error_type=type(exc).__name__)
            return set(self._fds)
        state_dir = Path(self._live.state_dir)
        return {install_folder.deciding_folder(state_dir, r.item_id).parent for r in installed}

    def _aim(self, wanted: Set[Path]) -> None:
        for folder in set(self._fds) - wanted:
            self._close(self._fds.pop(folder))
        for folder in wanted - set(self._fds):
            self._watch_one(folder)
        self._warned &= wanted

    def _watch_one(self, folder: Path) -> None:
        fd = -1
        try:
            fd = os.open(folder, _OPEN_FLAGS)
            event = select.kevent(fd, filter=select.KQ_FILTER_VNODE, flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR, fflags=_vnode_fflags())
            self._kq.control([event], 0, 0)
        except OSError as exc:
            self._close(fd)
            if folder not in self._warned:
                self._warned.add(folder)
                logger.warning("plugin_folder_not_watched", folder=str(folder), error_type=type(exc).__name__)
            return
        self._fds[folder] = fd

    @staticmethod
    def _close(fd: int) -> None:
        if fd < 0:
            return
        try:
            os.close(fd)
        except OSError:
            pass

    def _log_unsupported(self) -> None:
        if not self._unsupported_logged:
            self._unsupported_logged = True
            logger.warning("plugin_folder_watch_unavailable", reason="no_kqueue")

    def _on_readable(self) -> None:
        if self._kq is None:
            return
        try:
            events = self._kq.control(None, MAX_EVENTS, 0)
        except OSError as exc:
            logger.warning("plugin_folder_watch_drain_failed", error_type=type(exc).__name__)
            return
        if not events or self._loop is None:
            return
        if self._pending is None:
            self._pending = self._loop.create_task(self._settle_and_prune())
        else:
            self._dirty = True

    async def _settle_and_prune(self) -> None:
        try:
            while True:
                self._dirty = False
                gone = await self._gone_now()
                if gone:
                    await asyncio.sleep(self._settle)
                    await prune_gone.prune_pass(self._live, only=gone)
                await self._reaim()
                if not self._dirty:
                    break
        except OSError as exc:
            logger.warning("plugin_folder_watch_failed", error_type=type(exc).__name__)
        finally:
            self._pending = None

    async def _gone_now(self) -> Set[str]:
        try:
            states = await asyncio.to_thread(prune_gone.folder_states, self._live)
        except prune_gone.PRUNE_ERRORS as exc:
            logger.warning("plugin_folder_watch_ledger_unreadable", error_type=type(exc).__name__)
            return set()
        return {i for i, p in states.items() if p == GONE}
