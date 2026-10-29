"""What feeds the engine: the dirty set, and the classifier that turns a transcript path into a delivery target.

THE DIRTY SET is the engine's whole queue (decision 7 of the overhaul, #1682). A key is a transcript file (or a
conversation whose main transcript is gone); marking a key that is already pending changes nothing, so a file
appended to a hundred times between two deliveries is delivered once. Every key has an EARLIEST-ELIGIBLE TIME:

* a key delivered at ``t`` cannot be delivered again before ``t + MIN_INTERVAL_SECONDS`` (a streaming transcript
  is delivered about every 2 seconds, not on every append);
* a key whose FILE could not be read (a hung read, an iCloud placeholder) waits out an exponential backoff,
  ``BACKOFF_BASE_SECONDS`` doubling to ``BACKOFF_CAP_SECONDS``, and a later mark of the same key never shortens it;
* a PLUGIN that raised on a key waits out its own backoff for that key (failures are kept per key AND plugin), and
  only that plugin waits: a later live mark makes the key due again at the normal spacing and the engine leaves the
  failing plugin out until its own ``retry_at`` (``held``), so one plugin's poison file never slows another plugin
  on the same live conversation (R1 M2);
* a file that still has bytes after the run's byte budget goes straight back, behind everything already due.

``take`` hands out the keys that are due, LIVE keys first (an observer, a turn end or a feed mark: someone is
watching that conversation) and then the bulk ones (a scan, a rebuild replay), each group earliest-eligible first, so
a key that has waited longest goes first, one re-queued key never starves the rest (round robin) and a replay of
twenty thousand files never makes live freshness wait (R1 M4). Nothing is ever dropped: a key leaves the set only
when it was delivered (or its file is gone, which the scan reports as a removal).

``mark_*`` is O(1), takes one lock and reads no file: it is safe from the event loop, from ``fs_trigger``
callbacks and from the scan thread. ``Observer`` is the one door a watcher uses to say "this path changed".
"""

from __future__ import annotations

import heapq
import os
import threading
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

from src.core.pipeline import contract as C
from src.core.pipeline.deliver import FileTarget
from src.core.pipeline.subagent_tree import SubagentTreeIndex

MIN_INTERVAL_SECONDS: float = 2.0
BACKOFF_BASE_SECONDS: float = 5.0
BACKOFF_CAP_SECONDS: float = 300.0
_LAST_TAKEN_PRUNE_AT: int = 4096

TRIGGER_LIVE: str = "live"
TRIGGER_SCAN: str = "plugins"
TRIGGER_REBUILD: str = "rebuild"

KIND_FILE: str = "file"
KIND_REMOVED: str = "removed"
KIND_FILE_REMOVED: str = "file_removed"

Key = Tuple[str, str]
KEY_WIDE: str = ""


@dataclass
class Entry:
    """One pending key. ``target`` is None for a conversation removal (a file removal carries its file as ``target``).

    Attributes: key (kind, path or conversation id); conversation_id, family; trigger (what first marked it);
      rewritten (the manifest saw the file rewritten: open it even if the size equals the cursor); first_dirty (the
      clock reading of the first mark, kept across retries, so lag measures the real age); eligible_at; seq (the
      heap's tie-break and its staleness check); live (a live mark reached it: it is taken before bulk keys);
      backoff (it waits only for a failure's retry time, no new mark since).
    """

    key: Key
    target: Optional[FileTarget]
    conversation_id: str
    family: str
    trigger: str
    rewritten: bool
    first_dirty: float
    eligible_at: float = 0.0
    seq: int = 0
    live: bool = False
    backoff: bool = False


@dataclass(frozen=True)
class Failing:

    failures: int
    retry_at: float
    error: str
    plugins: Tuple[str, ...]


@dataclass(frozen=True)
class Waiting:

    conversation_id: str
    family: str
    trigger: str
    live: bool
    first_dirty: float
    eligible_at: float
    backoff: bool
    plugins: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DirtyView:

    pending: int
    oldest_first_dirty: Optional[float]
    by_family: Dict[str, Tuple[int, float]] = field(default_factory=dict)
    failing: Dict[Key, Failing] = field(default_factory=dict)
    parked: int = 0


class DirtySet:

    def __init__(self, clock: Callable[[], float], *, min_interval: float = MIN_INTERVAL_SECONDS,
                 backoff_base: float = BACKOFF_BASE_SECONDS, backoff_cap: float = BACKOFF_CAP_SECONDS) -> None:
        self._clock = clock
        self._min_interval = min_interval
        self._base = backoff_base
        self._cap = backoff_cap
        self._lock = threading.Lock()
        self._entries: Dict[Key, Entry] = {}
        self._live_heap: List[Tuple[float, int, Key]] = []
        self._bulk_heap: List[Tuple[float, int, Key]] = []
        self._last_taken: Dict[Key, float] = {}
        self._failing: Dict[Key, Dict[str, Failing]] = {}
        self._seq = 0

    def mark_file(self, target: FileTarget, trigger: str = TRIGGER_LIVE) -> bool:
        return self._mark((KIND_FILE, target.path), target, target.conversation_id, target.family, trigger,
                          target.rewritten)

    def mark_removed(self, conversation_id: str, family: str, trigger: str = TRIGGER_SCAN) -> bool:
        return self._mark((KIND_REMOVED, conversation_id), None, conversation_id, family, trigger, False)

    def mark_file_removed(self, target: FileTarget, trigger: str = TRIGGER_SCAN) -> bool:
        return self._mark((KIND_FILE_REMOVED, target.path), target, target.conversation_id, target.family, trigger, False)

    def _eligible(self, key: Key, now: float) -> float:
        last = self._last_taken.get(key)
        wide = self._failing.get(key, {}).get(KEY_WIDE)
        return max(now, last + self._min_interval if last is not None else now, wide.retry_at if wide else now)

    def _mark(self, key: Key, target: Optional[FileTarget], conversation_id: str, family: str, trigger: str,
              rewritten: bool) -> bool:
        now = self._clock()
        live = trigger == TRIGGER_LIVE
        with self._lock:
            pending = self._entries.get(key)
            if pending is not None:
                pending.rewritten = pending.rewritten or rewritten
                promote = live and not pending.live
                pull = pending.backoff and trigger != TRIGGER_SCAN and KEY_WIDE not in self._failing.get(key, {})
                if not (promote or pull):
                    return False
                self._push(replace(pending, live=pending.live or live, backoff=False), self._eligible(key, now))
                return True
            self._push(Entry(key, target, conversation_id, family, trigger, rewritten, now, live=live),
                       self._eligible(key, now))
            return True

    def _push(self, entry: Entry, eligible_at: float) -> None:
        old = self._entries.get(entry.key)
        self._seq += 1
        fresh = replace(entry, eligible_at=eligible_at, seq=self._seq)
        if old is not None:
            fresh.rewritten = fresh.rewritten or old.rewritten
            fresh.first_dirty = min(fresh.first_dirty, old.first_dirty)
            fresh.live = fresh.live or old.live
        self._entries[entry.key] = fresh
        heapq.heappush(self._live_heap if fresh.live else self._bulk_heap, (eligible_at, fresh.seq, entry.key))

    def take(self, limit: int, *, bulk: bool = True) -> List[Entry]:
        now = self._clock()
        out: List[Entry] = []
        with self._lock:
            for heap in ((self._live_heap, self._bulk_heap) if bulk else (self._live_heap,)):
                while heap and len(out) < limit:
                    eligible, seq, key = heap[0]
                    entry = self._entries.get(key)
                    if entry is None or entry.seq != seq:
                        heapq.heappop(heap)
                        continue
                    if eligible > now:
                        break
                    heapq.heappop(heap)
                    del self._entries[key]
                    self._last_taken[key] = now
                    out.append(entry)
            if len(self._last_taken) > _LAST_TAKEN_PRUNE_AT:
                horizon = now - self._min_interval
                self._last_taken = {k: t for k, t in self._last_taken.items() if t > horizon}
        return out

    def next_delay(self, *, bulk: bool = True) -> Optional[float]:
        now = self._clock()
        soonest: Optional[float] = None
        with self._lock:
            for heap in ((self._live_heap, self._bulk_heap) if bulk else (self._live_heap,)):
                while heap:
                    eligible, seq, key = heap[0]
                    entry = self._entries.get(key)
                    if entry is None or entry.seq != seq:
                        heapq.heappop(heap)
                        continue
                    soonest = eligible if soonest is None else min(soonest, eligible)
                    break
        return None if soonest is None else max(0.0, soonest - now)

    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def held(self, key: Key) -> FrozenSet[str]:
        now = self._clock()
        with self._lock:
            return frozenset(pid for pid, f in self._failing.get(key, {}).items() if pid != KEY_WIDE and f.retry_at > now)

    def settle(self, entry: Entry, *, ok: Iterable[str] = (), failures: Optional[Dict[str, str]] = None,
               file_error: Optional[str] = None, file_ok: bool = False, requeue: bool = False) -> float:
        """Record how one delivery of a key ended, and put the key back when anything still waits on it.

        Inputs: entry - the key just delivered; ok - plugins that ran and did not fail (their failure records go);
          failures - {plugin id: error} for plugins that raised (each backs off on its own: ``base * 2**(n-1)``,
          capped); file_error - the file itself could not be read (backs the whole key off); file_ok - the file was
          read this time (a file-level failure record goes); requeue - the run's byte budget ran out (back in, due
          now, behind what is already due).
        Output: the longest new backoff in seconds (0 when none). The key returns when it was requeued or any failure
          record remains, at the earliest of their retry times; a later mark never shortens a file-level wait.
        """
        now = self._clock()
        longest = 0.0
        with self._lock:
            records = self._failing.setdefault(entry.key, {})
            for pid in ok:
                records.pop(pid, None)
            if file_ok:
                records.pop(KEY_WIDE, None)
            new = dict(failures or {})
            if file_error is not None:
                new[KEY_WIDE] = file_error
            for pid, error in new.items():
                previous = records.get(pid)
                count = (previous.failures if previous else 0) + 1
                delay = min(self._cap, self._base * (2 ** min(count - 1, 30)))
                records[pid] = Failing(count, now + delay, error[:C.ERROR_CHARS], (pid,) if pid != KEY_WIDE else ())
                longest = max(longest, delay)
            if not records:
                del self._failing[entry.key]
            if requeue:
                self._push(replace(entry, backoff=False), now)
            elif records:
                self._push(replace(entry, backoff=True), min(f.retry_at for f in records.values()))
        return longest

    def forget_plugin(self, plugin_id: str) -> None:
        with self._lock:
            for key in list(self._failing):
                self._failing[key].pop(plugin_id, None)
                if not self._failing[key]:
                    del self._failing[key]

    def queue(self, limit: int) -> Tuple[List[Waiting], int]:
        now = self._clock()
        with self._lock:
            total = len(self._entries)
            first = heapq.nsmallest(max(0, int(limit)), self._entries.values(),
                                    key=lambda e: (max(e.eligible_at, now), not e.live, e.eligible_at, e.seq))
            out = [self._waiting(e) for e in first]
        return out, total

    def waiting_copies(self, entries: Sequence[Entry]) -> Tuple[Waiting, ...]:
        with self._lock:
            return tuple(self._waiting(e) for e in entries)

    def _waiting(self, e: Entry) -> Waiting:
        records = self._failing.get(e.key, {})
        held = () if not e.backoff or KEY_WIDE in records else tuple(sorted(records))
        return Waiting(e.conversation_id, e.family, e.trigger, e.live, e.first_dirty, e.eligible_at, e.backoff, held)

    def view(self) -> DirtyView:
        with self._lock:
            entries = list(self._entries.values())
            records = {k: dict(v) for k, v in self._failing.items()}
        by_family: Dict[str, Tuple[int, float]] = {}
        counts = Counter(e.family for e in entries)
        for family, n in counts.items():
            by_family[family] = (n, min(e.first_dirty for e in entries if e.family == family))
        oldest = min((e.first_dirty for e in entries), default=None)
        failing = {key: Failing(max(f.failures for f in found.values()), max(f.retry_at for f in found.values()),
                                max(found.values(), key=lambda f: f.retry_at).error,
                                tuple(sorted(pid for pid in found if pid != KEY_WIDE)))
                   for key, found in records.items()}
        return DirtyView(len(entries), oldest, by_family, failing, sum(1 for e in entries if e.backoff))


_UUID_CHARS: int = 36


def classify(path: str) -> Optional[FileTarget]:
    parts = Path(path).parts
    name = parts[-1] if parts else ""
    if not name.endswith(".jsonl"):
        return None
    if "subagents" in parts[:-1]:
        index = parts.index("subagents")
        return FileTarget(path, parts[index - 1], C.FAMILY_CLAUDE, C.FILE_SUBAGENT) if index > 0 else None
    if name.startswith("rollout-"):
        return FileTarget(path, name[:-len(".jsonl")][-_UUID_CHARS:], C.FAMILY_CODEX, C.FILE_CONVERSATION)
    return FileTarget(path, name[:-len(".jsonl")], C.FAMILY_CLAUDE, C.FILE_CONVERSATION)


class Observer:

    MAX_REMEMBERED: int = 20000

    def __init__(self, mark: Callable[[FileTarget, str], bool]) -> None:
        self._mark = mark
        self._sizes: Dict[str, int] = {}
        self._tree = SubagentTreeIndex()

    def file_changed(self, path: str, trigger: str = TRIGGER_LIVE) -> bool:
        target = classify(path)
        if target is None:
            return False
        self._mark(target, trigger)
        return True

    def session_changed(self, transcript: Optional[str], subagents_dir: Optional[str] = None,
                        trigger: str = TRIGGER_LIVE) -> int:
        paths: List[str] = [transcript] if transcript else []
        if subagents_dir and os.path.isdir(subagents_dir):
            paths.extend(self._tree.list_jsonl(subagents_dir))
        if len(self._sizes) > self.MAX_REMEMBERED:
            self._sizes.clear()
        marked = 0
        for path in paths:
            try:
                size = os.stat(path).st_size
            except OSError:
                continue
            if self._sizes.get(path) == size:
                continue
            self._sizes[path] = size
            marked += int(self.file_changed(path, trigger))
        return marked
