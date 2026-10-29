
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Dict, Optional, Set, Tuple

import structlog

from src.core.resource_push import notifier, topics
from src.core.session_git.repo_cache import RepoCache
from src.models.session_git import SessionGitStatus

logger = structlog.get_logger()

TICK_SECONDS: float = 5.0
LEASE_SECONDS: float = 45.0
KEEPALIVE_SECONDS: float = 20.0
_WORKING = frozenset({"working", "working_subagent"})
_RESTING = frozenset({"idle", "finished_unread"})


def signature(status: SessionGitStatus) -> str:
    return status.model_dump_json(exclude={"read_at"})


@dataclass
class _Viewer:

    directory: Path
    lease_until: float
    last_sig: Optional[str] = None
    last_named: float = 0.0


@dataclass
class _State:

    viewers: Dict[str, _Viewer] = field(default_factory=dict)
    last_status: Dict[str, str] = field(default_factory=dict)
    dirty: Set[str] = field(default_factory=set)


class GitStatusWatch:

    def __init__(
        self,
        cache: Optional[RepoCache] = None,
        *,
        notify: Callable[[str], None] = notifier.notify,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self.cache = cache or RepoCache(clock=clock)
        self._notify = notify
        self._sleep = sleep
        self._s = _State()
        self._task: Optional["asyncio.Task[None]"] = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def read(self, session_id: str, directory: Path) -> SessionGitStatus:
        now = self._clock()
        viewer = self._s.viewers.get(session_id)
        if viewer is None:
            viewer = self._s.viewers[session_id] = _Viewer(directory, now + LEASE_SECONDS)
        viewer.directory, viewer.lease_until = directory, now + LEASE_SECONDS
        if not self.running:
            self._task = asyncio.get_running_loop().create_task(self._run())
        status, _ = await self.cache.get(directory)
        viewer.last_sig, viewer.last_named = signature(status), self._clock()
        return status

    def on_status(self, session_id: str, display: str) -> None:
        previous = self._s.last_status.get(session_id)
        if display in _WORKING:
            self._s.last_status[session_id] = display
        else:
            self._s.last_status.pop(session_id, None)
        if session_id in self._s.viewers and previous in _WORKING and display in _RESTING:
            self._s.dirty.add(session_id)

    async def _tick(self) -> bool:
        now = self._clock()
        s = self._s
        s.viewers = {k: v for k, v in s.viewers.items() if v.lease_until > now}
        if not s.viewers:
            return False
        groups: Dict[str, Tuple[Path, list]] = {}
        for sid, viewer in s.viewers.items():
            groups.setdefault(self.cache.key_of(viewer.directory), (viewer.directory, []))[1].append(sid)
        self.cache.retain(set(groups))
        for directory, sids in groups.values():
            force = any(sid in s.dirty for sid in sids)
            try:
                status, spawned = await self.cache.get(directory, force=force)
            except (OSError, RuntimeError) as exc:
                logger.warning("git_status_watch_read_failed", error=type(exc).__name__)
                continue
            if spawned or not force:
                s.dirty.difference_update(sids)
            try:
                sig = signature(status)
            except ValueError as exc:
                logger.warning("git_status_watch_signature_failed", error=type(exc).__name__)
                continue
            for sid in sids:
                viewer = s.viewers[sid]
                if viewer.last_sig is None:
                    viewer.last_sig, viewer.last_named = sig, self._clock()
                elif sig != viewer.last_sig or self._clock() - viewer.last_named >= KEEPALIVE_SECONDS:
                    viewer.last_sig, viewer.last_named = sig, self._clock()
                    self._notify(topics.keyed(topics.GIT_STATUS, sid))
        return True

    async def _run(self) -> None:
        try:
            while True:
                await self._sleep(TICK_SECONDS)
                try:
                    live = await self._tick()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("git_status_watch_tick_failed", error=type(exc).__name__,
                                   sessions=sorted(self._s.viewers),
                                   repos=sorted({str(v.directory) for v in self._s.viewers.values()}))
                    continue
                if not live:
                    break
        finally:
            self.cache.retain(set())
            self._s.dirty.clear()
            logger.debug("git_status_watch_idle")

    async def stop(self) -> None:
        self._s.viewers.clear()
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
