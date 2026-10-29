"""Remember where we stopped reading a transcript, and resume from there.

THE CACHE IS AN OPTIMISATION AND MAY NEVER BECOME A DEPENDENCY. Every
miss and every doubt rescans from byte zero. A rescan is slow, never
wrong; a bad resume is fast and wrong, and wrong here means a cost
figure a user acts on.

TWO INDEPENDENT DOUBTS FORCE A RESCAN, AND EITHER ONE IS ENOUGH.

  THE FILE SHRANK, or its size fell below the offset we stopped at. An
    append-only file does not shrink, so this is a different file under
    the same path - a session cleared, a transcript rewritten, a fork.
  THE HEAD CHANGED. We keep the first 256 bytes and compare them. A file
    truncated and rewritten to the SAME length would pass a size check
    and fail this one. It is cheap (one read of 256 bytes) and it is the
    only guard against a same-size replacement.

An unchanged size AND an unchanged head with a matching mtime is a hit
that reads nothing at all, which is the steady state while a session is
idle.

AN UNCHANGED STAT SIGNATURE IS A HIT THAT OPENS NOTHING. A caller that
passes ``signature`` (inode, size, mtime_ns, ctime_ns, from
:func:`stat_signature`) to ``remember`` may ask :meth:`unchanged` before
opening the file. ``ctime`` cannot be set back by ``utime``, so a file
rewritten to the same length still fails this check, and the head
comparison above stays the guard for every read that does open the file.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field, replace
import os
import threading
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from src.core.session_token_usage.claude_selection import ULTRACODE
from src.core.session_token_usage.persist_spec import PersistSpec
from src.core.session_token_usage.totals_codec import TRANSCRIPT_TOTALS_SPEC

HEAD_BYTES = 256

MAX_ENTRIES = 256


@dataclass(frozen=True)
class TranscriptTotals:

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    last_usage: Optional[Dict[str, Any]] = None
    last_model: Optional[str] = None
    last_effort: Optional[str] = None
    last_model_display: Optional[str] = None
    last_message_id: Optional[str] = None
    malformed_lines: int = 0
    ultra_effort: bool = False

    @property
    def effective_effort(self) -> Optional[str]:
        return ULTRACODE if self.ultra_effort else self.last_effort

    def plus_ultra(self, entered: bool) -> "TranscriptTotals":
        return replace(self, ultra_effort=entered)

    def plus_usage(
        self,
        usage: Dict[str, Any],
        *,
        model: Optional[str],
        effort: Optional[str] = None,
        message_id: Optional[str],
    ) -> "TranscriptTotals":
        return TranscriptTotals(
            input_tokens=self.input_tokens + coerce_token_count(usage.get("input_tokens")),
            output_tokens=self.output_tokens + coerce_token_count(usage.get("output_tokens")),
            cache_read_input_tokens=(
                self.cache_read_input_tokens
                + coerce_token_count(usage.get("cache_read_input_tokens"))
            ),
            cache_creation_input_tokens=(
                self.cache_creation_input_tokens
                + coerce_token_count(usage.get("cache_creation_input_tokens"))
            ),
            last_usage=usage,
            last_model=model if model else self.last_model,
            last_effort=effort if model else (effort or self.last_effort),
            last_model_display=None if model else self.last_model_display,
            last_message_id=message_id,
            malformed_lines=self.malformed_lines,
            ultra_effort=self.ultra_effort,
        )

    def plus_selection(
        self,
        *,
        model: Optional[str],
        model_display: Optional[str],
        effort: Optional[str],
        ultra: Optional[bool] = None,
    ) -> "TranscriptTotals":
        if model:
            last_model, last_display = model, None
        elif model_display:
            last_model, last_display = self.last_model, model_display
        else:
            last_model, last_display = self.last_model, self.last_model_display
        return replace(
            self,
            last_model=last_model,
            last_model_display=last_display,
            last_effort=effort if effort else self.last_effort,
            ultra_effort=self.ultra_effort if ultra is None else ultra,
        )

    def plus_malformed(self) -> "TranscriptTotals":
        return replace(self, malformed_lines=self.malformed_lines + 1)


def coerce_token_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))


StatSignature = Tuple[int, int, int, int]


def stat_signature(stat: os.stat_result) -> StatSignature:
    return (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


@dataclass(frozen=True)
class CacheEntry:

    size: int
    mtime_ns: int
    offset: int
    head: bytes
    totals: TranscriptTotals
    signature: Optional[StatSignature] = None


@dataclass
class IncrementalCache:

    _entries: "OrderedDict[str, CacheEntry]" = field(default_factory=OrderedDict)
    max_entries: int = MAX_ENTRIES
    persist: Optional[PersistSpec] = None
    _lock: Any = field(default_factory=threading.RLock, repr=False, compare=False)
    _dirty: Dict[str, Optional[CacheEntry]] = field(
        default_factory=dict, repr=False, compare=False
    )
    _tracking: bool = field(default=False, repr=False, compare=False)

    def track_dirty(self, on: bool) -> None:
        with self._lock:
            self._tracking = bool(on) and self.persist is not None
            if not self._tracking:
                self._dirty.clear()

    def _mark(self, path: str, entry: Optional[CacheEntry]) -> None:
        if self._tracking:
            self._dirty[path] = entry

    def _evict_over_bound(self) -> None:
        while len(self._entries) > self.max_entries:
            evicted, _ = self._entries.popitem(last=False)
            self._mark(evicted, None)

    def drain_dirty(self) -> Dict[str, Optional[CacheEntry]]:
        with self._lock:
            drained, self._dirty = self._dirty, {}
        return drained

    def requeue(self, items: Mapping[str, Optional[CacheEntry]]) -> None:
        with self._lock:
            if not self._tracking:
                return
            for path, entry in items.items():
                self._dirty.setdefault(path, entry)

    def hydrate(self, entries: Sequence[Tuple[str, CacheEntry]]) -> int:
        loaded = 0
        with self._lock:
            for path, entry in reversed(entries):
                if path in self._entries:
                    continue
                self._entries[path] = entry
                self._entries.move_to_end(path, last=False)
                loaded += 1
            self._evict_over_bound()
        return loaded

    def forget(self, path: str) -> None:
        with self._lock:
            if self._entries.pop(path, None) is not None:
                self._mark(path, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._dirty.clear()

    def unchanged(self, path: str, signature: StatSignature) -> Optional[Any]:
        with self._lock:
            entry = self._entries.get(path)
            if entry is None or entry.signature is None or entry.signature != signature:
                return None
            self._entries.move_to_end(path)
            return entry.totals

    def knows(self, path: str) -> bool:
        with self._lock:
            return str(path) in self._entries

    def resume_point(
        self, path: str, *, size: int, mtime_ns: int, head: bytes
    ) -> Optional[Tuple[int, TranscriptTotals]]:
        with self._lock:
            entry = self._entries.get(path)
            if entry is None:
                return None
            if size < entry.size or size < entry.offset or head != entry.head:
                del self._entries[path]
                self._mark(path, None)
                return None
            self._entries.move_to_end(path)
            return entry.offset, entry.totals

    def remember(
        self,
        path: str,
        *,
        size: int,
        mtime_ns: int,
        head: bytes,
        offset: int,
        totals: TranscriptTotals,
        signature: Optional[StatSignature] = None,
    ) -> None:
        entry = CacheEntry(
            size=size, mtime_ns=mtime_ns, offset=offset, head=head, totals=totals,
            signature=signature,
        )
        with self._lock:
            self._entries[path] = entry
            self._entries.move_to_end(path)
            self._mark(path, entry)
            self._evict_over_bound()


TRANSCRIPT_CACHE = IncrementalCache(persist=TRANSCRIPT_TOTALS_SPEC)
