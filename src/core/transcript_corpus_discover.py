
from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

HASH_CHUNK_SIZE = 4 * 1024 * 1024

SUBAGENTS_DIRNAME = "subagents"

OUTCOME_SAMPLE_LIMIT = 50


@dataclass(frozen=True)
class CorpusEntry:

    abs_path: Path
    source_path: str
    kind: str


def default_corpus_root() -> Path:
    return Path.home() / ".claude" / "projects"


@dataclass
class DiscoveryOutcome:

    entries: List[CorpusEntry] = field(default_factory=list)
    unrecognised_count: int = 0
    unrecognised_sample: List[str] = field(default_factory=list)
    unreadable_count: int = 0
    unreadable_sample: List[Dict[str, str]] = field(default_factory=list)


def _note(count: int, sample: list, value) -> int:
    if len(sample) < OUTCOME_SAMPLE_LIMIT:
        sample.append(value)
    return count + 1


TRUST_AFTER_NS = 2_000_000_000

MAX_CACHED_DIRS = 50_000

_FILE, _DIR, _OTHER = "f", "d", "o"
_Listing = Tuple[Tuple[str, str], ...]
_Item = Tuple[int, Any, Optional[str], Optional[Path]]
_Items = Tuple[_Item, ...]
_ENTRY, _UNRECOGNISED, _SUBDIR = 0, 1, 2
_JSONL = ".jsonl"


def _kind_of(item: Path) -> str:
    if item.is_file():
        return _FILE
    return _DIR if item.is_dir() else _OTHER


def _entry_kind(entry: "os.DirEntry[str]") -> str:
    try:
        if entry.is_file():
            return _FILE
        return _DIR if entry.is_dir() else _OTHER
    except OSError:
        return _kind_of(Path(entry.path))


def _list_dir(path: Path) -> _Listing:
    with os.scandir(path) as scan:
        return tuple(sorted((entry.name, _entry_kind(entry)) for entry in scan))


class DirListingCache:

    def __init__(self, *, max_dirs: int = MAX_CACHED_DIRS) -> None:
        self._max = max_dirs
        self._lock = threading.Lock()
        self._dirs: Dict[str, Tuple[int, _Listing, Dict[Any, Any]]] = {}

    def _lookup(self, path: Path) -> Tuple[_Listing, Dict[Any, Any]]:
        key = str(path)
        mtime = os.stat(path).st_mtime_ns
        with self._lock:
            hit = self._dirs.get(key)
        if hit is not None and hit[0] == mtime and time.time_ns() - mtime > TRUST_AFTER_NS:
            return hit[1], hit[2]
        entries = _list_dir(path)
        slot: Dict[Any, Any] = {}
        with self._lock:
            if len(self._dirs) >= self._max:
                self._dirs.clear()
            self._dirs[key] = (mtime, entries, slot)
        return entries, slot

    def listing(self, path: Path) -> _Listing:
        return self._lookup(path)[0]

    def derived(self, path: Path, key: Any, build: Callable[[_Listing], Any]) -> Any:
        listing, slot = self._lookup(path)
        try:
            return slot[key]
        except KeyError:
            return slot.setdefault(key, build(listing))


def _build_items(path: Path, prefix: str, entry_kind: str, listing: _Listing) -> _Items:
    items: List[_Item] = []
    for name, kind in listing:
        if kind == _FILE:
            source = f"{prefix}/{name}"
            if name.endswith(_JSONL) and len(name) > len(_JSONL):
                items.append((_ENTRY, CorpusEntry(abs_path=path / name, source_path=source, kind=entry_kind), None, None))
            else:
                items.append((_UNRECOGNISED, source, None, None))
        elif kind == _DIR:
            child = path / name
            items.append((_SUBDIR, child, name, child / SUBAGENTS_DIRNAME if entry_kind == "session" else None))
    return tuple(items)


def _iter_dir(
    path: Path, outcome: DiscoveryOutcome, cache: Optional[DirListingCache] = None,
) -> Optional[List[Tuple[Path, str]]]:
    try:
        if cache is not None:
            return [(path / name, kind) for name, kind in cache.listing(path)]
        return [(item, _kind_of(item)) for item in sorted(path.iterdir())]
    except OSError as exc:
        outcome.unreadable_count = _note(
            outcome.unreadable_count,
            outcome.unreadable_sample,
            {"path": str(path), "reason": str(exc)},
        )
        return None


def _classify_dir(
    path: Path, prefix: str, entry_kind: str, outcome: DiscoveryOutcome, cache: Optional[DirListingCache] = None,
) -> Optional[_Items]:
    try:
        if cache is not None:
            return cache.derived(path, (prefix, entry_kind),
                                 lambda listing: _build_items(path, prefix, entry_kind, listing))
        return _build_items(path, prefix, entry_kind, _list_dir(path))
    except OSError as exc:
        outcome.unreadable_count = _note(
            outcome.unreadable_count,
            outcome.unreadable_sample,
            {"path": str(path), "reason": str(exc)},
        )
        return None


def walk_subagents(
    sub: Path, prefix: str, outcome: DiscoveryOutcome,
    cache: Optional[DirListingCache] = None,
) -> None:
    items = _classify_dir(sub, prefix, "subagent", outcome, cache)
    if items is None:
        return
    for tag, value, name, _ in items:
        if tag == _ENTRY:
            outcome.entries.append(value)
        elif tag == _UNRECOGNISED:
            outcome.unrecognised_count = _note(outcome.unrecognised_count, outcome.unrecognised_sample, value)
        else:
            walk_subagents(value, f"{prefix}/{name}", outcome, cache)


def discover_corpus_detailed(
    corpus_root: Path, cache: Optional[DirListingCache] = None,
) -> DiscoveryOutcome:
    outcome = DiscoveryOutcome()
    corpus_root = Path(corpus_root)
    if not corpus_root.is_dir():
        return outcome

    top = _classify_dir(corpus_root, "", "session", outcome, cache)
    if top is None:
        return outcome
    for tag, slug_dir, slug, _ in top:
        if tag != _SUBDIR:
            continue
        listing = _classify_dir(slug_dir, slug, "session", outcome, cache)
        if listing is None:
            continue
        for item_tag, value, name, sub in listing:
            if item_tag == _ENTRY:
                outcome.entries.append(value)
            elif item_tag == _UNRECOGNISED:
                outcome.unrecognised_count = _note(outcome.unrecognised_count, outcome.unrecognised_sample, value)
            elif not sub.is_dir():
                outcome.unrecognised_count = _note(
                    outcome.unrecognised_count,
                    outcome.unrecognised_sample,
                    f"{slug}/{name}",
                )
            else:
                walk_subagents(sub, f"{slug}/{name}/{SUBAGENTS_DIRNAME}", outcome, cache)
    return outcome


def discover_corpus(corpus_root: Path) -> List[CorpusEntry]:
    return discover_corpus_detailed(corpus_root).entries


def hash_file(path: Path) -> tuple:
    hasher = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(HASH_CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(chunk)
            size += len(chunk)
    return hasher.hexdigest(), size


def mtime_iso(path: Path) -> Optional[str]:
    try:
        ts = os.stat(path).st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
