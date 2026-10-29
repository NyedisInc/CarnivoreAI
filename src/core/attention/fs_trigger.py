
from __future__ import annotations

import asyncio
import os
import resource
import select
import time
from collections import OrderedDict
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Set

import structlog

logger = structlog.get_logger()

KQUEUE_AVAILABLE: bool = hasattr(select, "kqueue")

DEBOUNCE_QUIET_SECONDS: float = 0.15

DEBOUNCE_MAX_SECONDS: float = 1.0

MAX_WATCHED_PATHS: int = 64

FD_BUDGET_DIVISOR: int = 4

DRAIN_BATCH: int = 64

_O_EVENT_ONLY: int = getattr(os, "O_EVTONLY", os.O_RDONLY)
_GONE_FLAGS: int = (
    getattr(select, "KQ_NOTE_DELETE", 0)
    | getattr(select, "KQ_NOTE_RENAME", 0)
    | getattr(select, "KQ_NOTE_REVOKE", 0)
)
_CHANGE_FLAGS: int = (
    getattr(select, "KQ_NOTE_WRITE", 0) | getattr(select, "KQ_NOTE_EXTEND", 0)
    | _GONE_FLAGS
)


class Coalescer:

    def __init__(self, quiet: float, max_wait: float) -> None:
        self.quiet = quiet
        self.max_wait = max_wait
        self._keys: Set[str] = set()
        self._first: Optional[float] = None
        self._last: Optional[float] = None

    def note(self, keys: Iterable[str], now: float) -> None:
        added = set(keys)
        if not added:
            return
        self._keys |= added
        if self._first is None:
            self._first = now
        self._last = now

    def due_at(self) -> Optional[float]:
        if self._first is None or self._last is None:
            return None
        return min(self._last + self.quiet, self._first + self.max_wait)

    def take(self, now: float) -> Set[str]:
        due = self.due_at()
        if due is None or now < due:
            return set()
        keys, self._keys = self._keys, set()
        self._first = self._last = None
        return keys


def descriptor_budget(max_paths: int = MAX_WATCHED_PATHS) -> int:
    try:
        soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    except (OSError, ValueError):
        return max_paths
    if soft == resource.RLIM_INFINITY or soft <= 0:
        return max_paths
    return max(0, min(max_paths, soft // FD_BUDGET_DIVISOR))


class FsTrigger:

    def __init__(
        self,
        on_fire: Callable[[Set[str]], None],
        *,
        quiet_seconds: float = DEBOUNCE_QUIET_SECONDS,
        max_wait_seconds: float = DEBOUNCE_MAX_SECONDS,
        max_paths: Optional[int] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._on_fire = on_fire
        self._coalescer = Coalescer(quiet_seconds, max_wait_seconds)
        self._cap = descriptor_budget() if max_paths is None else max(0, max_paths)
        self._clock = clock
        self._kq: Optional["select.kqueue"] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._timer: Optional[asyncio.TimerHandle] = None
        self._watches: "OrderedDict[str, int]" = OrderedDict()
        self._paths_by_fd: Dict[int, str] = {}
        self._keys_by_path: Dict[str, Set[str]] = {}
        self._last_event: Dict[str, float] = {}
        self._failure_logged = False
        self.fired = 0

    @property
    def active(self) -> bool:
        return self._kq is not None

    @property
    def capacity(self) -> int:
        return self._cap

    def watched_paths(self) -> List[str]:
        return list(self._watches)

    def start(self) -> bool:
        if self._kq is not None:
            return True
        if not KQUEUE_AVAILABLE:
            self._log_unavailable("no_kqueue")
            return False
        if self._cap <= 0:
            self._log_unavailable("no_descriptor_budget")
            return False
        kq = None
        try:
            loop = asyncio.get_running_loop()
            kq = select.kqueue()
            loop.add_reader(kq.fileno(), self._on_readable)
        except (OSError, ValueError, NotImplementedError, RuntimeError) as exc:
            if kq is not None:
                try:
                    kq.close()
                except OSError:
                    pass
            self._log_unavailable(type(exc).__name__, error=str(exc))
            return False
        self._kq, self._loop = kq, loop
        return True

    def rearm(self, desired: Mapping[str, Iterable[str]]) -> None:
        """Make the watched set match ``desired``, within the cap.

        Description: closes watches no longer wanted, opens new ones, and
          when more paths are wanted than the cap allows keeps the ones
          with the most recent events (ties keep what is already
          watched, so a full set does not churn descriptors every pass).
          A path that cannot be opened (not created yet, or gone) is
          skipped quietly; the next rearm retries it.
        Inputs: desired - path -> session ids read from that path.
        Output: None.
        """
        if self._kq is None:
            return
        wanted = {path: set(keys) for path, keys in desired.items() if path}
        for path in [p for p in self._last_event if p not in wanted]:
            del self._last_event[path]
        chosen = self._select(list(wanted))
        for path in [p for p in self._watches if p not in chosen]:
            self._unwatch(path)
        self._keys_by_path = {path: wanted[path] for path in chosen}
        for path in chosen:
            if path not in self._watches:
                self._watch(path)

    def close(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        for path in list(self._watches):
            self._unwatch(path)
        kq, loop = self._kq, self._loop
        self._kq = self._loop = None
        if kq is not None:
            if loop is not None:
                try:
                    loop.remove_reader(kq.fileno())
                except (OSError, ValueError, RuntimeError):
                    pass
            try:
                kq.close()
            except OSError:
                pass


    def _select(self, paths: List[str]) -> Set[str]:
        if len(paths) <= self._cap:
            return set(paths)
        ranked = sorted(
            paths,
            key=lambda p: (self._last_event.get(p, 0.0), p in self._watches),
            reverse=True,
        )
        return set(ranked[: self._cap])

    def _watch(self, path: str) -> bool:
        try:
            fd = os.open(path, _O_EVENT_ONLY)
        except FileNotFoundError:
            return False
        except OSError as exc:
            logger.debug("attention_fs_watch_open_failed", path=path, error=str(exc))
            return False
        try:
            self._kq.control([select.kevent(
                fd, filter=select.KQ_FILTER_VNODE,
                flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR, fflags=_CHANGE_FLAGS,
            )], 0, 0)
        except OSError as exc:
            os.close(fd)
            logger.debug("attention_fs_watch_register_failed", path=path, error=str(exc))
            return False
        self._watches[path] = fd
        self._paths_by_fd[fd] = path
        return True

    def _unwatch(self, path: str) -> None:
        fd = self._watches.pop(path, None)
        if fd is None:
            return
        self._paths_by_fd.pop(fd, None)
        try:
            os.close(fd)
        except OSError:
            pass

    def _on_readable(self) -> None:
        kq = self._kq
        if kq is None:
            return
        try:
            events = kq.control(None, DRAIN_BATCH, 0)
        except OSError as exc:
            self._log_unavailable("drain_failed", error=str(exc))
            self.close()
            return
        now = self._clock()
        keys: Set[str] = set()
        for event in events:
            path = self._paths_by_fd.get(event.ident)
            if path is None:
                continue
            keys |= self._keys_by_path.get(path, set())
            self._last_event[path] = now
            if path in self._watches:
                self._watches.move_to_end(path)
            if event.fflags & _GONE_FLAGS:
                self._unwatch(path)
        if keys:
            self._coalescer.note(keys, now)
            self._schedule()

    def _schedule(self) -> None:
        loop, due = self._loop, self._coalescer.due_at()
        if loop is None or due is None:
            return
        if self._timer is not None:
            self._timer.cancel()
        self._timer = loop.call_later(max(0.0, due - self._clock()), self._release)

    def _release(self) -> None:
        self._timer = None
        keys = self._coalescer.take(self._clock())
        if not keys:
            self._schedule()
            return
        self.fired += 1
        try:
            self._on_fire(keys)
        except Exception as exc:  # noqa: BLE001
            logger.warning("attention_fs_trigger_callback_failed",
                           error=str(exc), error_type=type(exc).__name__)

    def _log_unavailable(self, reason: str, **fields: str) -> None:
        if self._failure_logged:
            return
        self._failure_logged = True
        logger.info("attention_fs_trigger_unavailable", reason=reason, **fields)
