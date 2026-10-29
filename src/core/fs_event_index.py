
from __future__ import annotations

import asyncio
import os
import re
import threading
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional, Set, Tuple

import structlog

logger = structlog.get_logger()

RESCAN_SECONDS: float = 60.0

DEBOUNCE_MS: int = 150
STEP_MS: int = 100

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_FILE_RE = re.compile(r"(?:^|-)(%s)\.jsonl$" % _UUID, re.IGNORECASE)

Entry = Tuple[str, int, float]
Key = Tuple[str, str]

CLAUDE = "claude"
CODEX = "codex"

RESYNC = "*"

ARM_SETTLE_SECONDS: float = 0.3


def key_of(path: str) -> Optional[Key]:
    name = os.path.basename(path)
    uuid = uuid_of(name)
    if uuid is None:
        return None
    return (CODEX if name.startswith("rollout-") else CLAUDE, uuid)


def uuid_of(path: str) -> Optional[str]:
    match = _FILE_RE.search(os.path.basename(path))
    return match.group(1).lower() if match else None


class FsEventIndex:

    def __init__(self, roots: Iterable[str], *, rescan_seconds: float = RESCAN_SECONDS) -> None:
        self.roots = tuple(os.path.abspath(str(r)) for r in roots)
        self._rescan_seconds = rescan_seconds
        self._entries: Dict[Key, Entry] = {}
        self._lock = threading.Lock()
        self._touched: Optional[Set[Key]] = None
        self._subscribers: Dict[int, Callable[[Set[str]], None]] = {}
        self._next_token = 0
        self.ready = False
        self.watching = False
        self._watched: Tuple[str, ...] = ()
        self._target: Tuple[str, ...] = ()
        self._stop = asyncio.Event()
        self._rewatch = asyncio.Event()


    @staticmethod
    def _under(path: str, roots: Iterable[str]) -> bool:
        p = os.path.abspath(path)
        return any(p == r or p.startswith(r + os.sep) for r in roots)

    def covers(self, path: str) -> bool:
        return self._under(path, self.roots)

    def serves(self, path: str) -> bool:
        return self.watching and self._under(path, self._watched)

    def lookup(self, uuid: str, kind: str = CODEX) -> Optional[str]:
        entry = self.entry(uuid, kind)
        return entry[0] if entry else None

    def entry(self, uuid: str, kind: str = CODEX) -> Optional[Entry]:
        with self._lock:
            return self._entries.get((kind, str(uuid).lower()))

    def subscribe(self, callback: Callable[[Set[str]], None]) -> Callable[[], None]:
        token = self._next_token
        self._next_token += 1
        self._subscribers[token] = callback
        return lambda: self._subscribers.pop(token, None) and None


    def _apply(self, path: str) -> None:
        key = key_of(path)
        if key is None:
            return
        try:
            st = os.stat(path)
        except OSError:
            with self._lock:
                if self._touched is not None:
                    self._touched.add(key)
                if self._entries.get(key, ("",))[0] == path:
                    del self._entries[key]
            return
        with self._lock:
            if self._touched is not None:
                self._touched.add(key)
            prior = self._entries.get(key)
            if prior is None or path >= prior[0]:
                self._entries[key] = (path, st.st_size, st.st_mtime)

    def _scan(self) -> None:
        seen: Dict[Key, Entry] = {}
        with self._lock:
            known = dict(self._entries)
            self._touched = set()
        try:
            self._walk(seen, known)
        finally:
            with self._lock:
                touched, self._touched = self._touched or set(), None
                for key in touched:
                    if key in self._entries:
                        seen[key] = self._entries[key]
                    else:
                        seen.pop(key, None)
                self._entries = seen

    def _walk(self, seen: Dict[Key, Entry], known: Dict[Key, Entry]) -> None:
        stack = [r for r in self.roots if os.path.isdir(r)]
        while stack:
            directory = stack.pop()
            try:
                with os.scandir(directory) as it:
                    for item in it:
                        try:
                            if item.is_dir(follow_symlinks=False):
                                stack.append(item.path)
                                continue
                        except OSError:
                            continue
                        key = key_of(item.name)
                        if key is None:
                            continue
                        try:
                            st = item.stat()
                        except OSError:
                            continue
                        prior = seen.get(key)
                        if prior is None or item.path >= prior[0]:
                            seen[key] = (item.path, st.st_size, st.st_mtime)
            except OSError:
                for key, prior in known.items():
                    if os.path.dirname(prior[0]) == directory:
                        seen.setdefault(key, prior)

    def _notify(self, paths: Set[str]) -> None:
        for callback in list(self._subscribers.values()):
            try:
                callback(paths)
            except Exception as exc:  # noqa: BLE001
                logger.warning("fs_event_index_subscriber_failed", error=str(exc))

    def _present_roots(self) -> Tuple[str, ...]:
        return tuple(r for r in self.roots if os.path.isdir(r))

    async def _rescan_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self._scan)
                first = not self.ready
                self.ready = True
                if first:
                    logger.info("fs_event_index_scanned", entries=len(self._entries), roots=list(self._present_roots()))
            except Exception as exc:  # noqa: BLE001
                logger.warning("fs_event_index_scan_failed", error=str(exc))
            if self._present_roots() != self._target:
                self._rewatch.set()
            try:
                await asyncio.wait_for(self._stop.wait(), self._rescan_seconds)
            except asyncio.TimeoutError:
                pass

    async def _wait_stop_or_rewatch(self) -> None:
        waits = [asyncio.ensure_future(self._stop.wait()), asyncio.ensure_future(self._rewatch.wait())]
        try:
            await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for w in waits:
                w.cancel()

    async def _watch_once(self, roots: Tuple[str, ...]) -> None:
        from watchfiles import awatch

        done = asyncio.Event()

        async def either() -> None:
            await self._wait_stop_or_rewatch()
            done.set()

        guard = asyncio.ensure_future(either())
        stream = awatch(*roots, stop_event=done, debounce=DEBOUNCE_MS, step=STEP_MS, ignore_permission_denied=True).__aiter__()
        pending = asyncio.ensure_future(stream.__anext__())
        try:
            await asyncio.sleep(ARM_SETTLE_SECONDS)
            self._watched, self.watching = roots, True
            logger.info(
                "fs_event_index_watching", roots=list(roots),
                missing=[r for r in self.roots if r not in roots], rescan_seconds=self._rescan_seconds,
            )
            self._notify({RESYNC})
            while True:
                try:
                    changes = await pending
                except StopAsyncIteration:
                    return
                pending = asyncio.ensure_future(stream.__anext__())
                paths = {p for _kind, p in changes}
                for path in paths:
                    self._apply(path)
                self._notify(paths)
        finally:
            self.watching = False
            pending.cancel()
            guard.cancel()
            self._notify({RESYNC})

    async def _watch_loop(self) -> None:
        try:
            import watchfiles  # noqa: F401
        except ImportError:
            logger.info("fs_event_index_unavailable", reason="no_watchfiles")
            return
        while not self._stop.is_set():
            self._rewatch.clear()
            roots = self._target = self._present_roots()
            try:
                if roots:
                    await self._watch_once(roots)
                else:
                    logger.info("fs_event_index_waiting_for_roots", roots=list(self.roots))
                    await self._wait_stop_or_rewatch()
                    continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("fs_event_index_watch_failed", error=str(exc))
            if not self._stop.is_set() and not self._rewatch.is_set():
                await asyncio.sleep(min(self._rescan_seconds, 5.0))

    async def run(self) -> None:
        await asyncio.gather(self._rescan_loop(), self._watch_loop())

    def stop(self) -> None:
        self._stop.set()


_index: Optional[FsEventIndex] = None
_task: Optional["asyncio.Task[None]"] = None


def default_roots() -> Tuple[str, str]:
    from src.core.attention.codex_gather import DEFAULT_CODEX_HOME

    return (
        str(Path.home() / ".claude" / "projects"),
        os.path.join(os.path.expanduser(DEFAULT_CODEX_HOME), "sessions"),
    )


def start() -> FsEventIndex:
    global _index, _task
    loop = asyncio.get_running_loop()
    if _index is None or _task is None or _task.done() or _task.get_loop() is not loop:
        _index = FsEventIndex(default_roots(), rescan_seconds=RESCAN_SECONDS)
        _task = loop.create_task(_index.run(), name="fs-event-index")
    return _index


def current() -> Optional[FsEventIndex]:
    return _index
