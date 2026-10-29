
from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HASH_CHUNK_SIZE = 4 * 1024 * 1024

SUBAGENTS_DIRNAME = "subagents"

OUTCOME_SAMPLE_LIMIT = 50


@dataclass
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


def _kind_of(item: Path) -> str:
    if item.is_file():
        return _FILE
    return _DIR if item.is_dir() else _OTHER


class DirListingCache:

    def __init__(self, *, max_dirs: int = MAX_CACHED_DIRS) -> None:
        self._max = max_dirs
        self._lock = threading.Lock()
        self._dirs: Dict[str, Tuple[int, _Listing]] = {}

    def listing(self, path: Path) -> _Listing:
        key = str(path)
        mtime = os.stat(path).st_mtime_ns
        with self._lock:
            hit = self._dirs.get(key)
        if hit is not None and hit[0] == mtime and time.time_ns() - mtime > TRUST_AFTER_NS:
            return hit[1]
        entries = tuple(sorted((item.name, _kind_of(item)) for item in path.iterdir()))
        with self._lock:
            if len(self._dirs) >= self._max:
                self._dirs.clear()
            self._dirs[key] = (mtime, entries)
        return entries


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


def walk_subagents(
    sub: Path, prefix: str, outcome: DiscoveryOutcome,
    cache: Optional[DirListingCache] = None,
) -> None:
    listing = _iter_dir(sub, outcome, cache)
    if listing is None:
        return
    for item, kind in listing:
        if kind == _FILE:
            if item.suffix == ".jsonl":
                outcome.entries.append(
                    CorpusEntry(
                        abs_path=item,
                        source_path=f"{prefix}/{item.name}",
                        kind="subagent",
                    )
                )
            else:
                outcome.unrecognised_count = _note(
                    outcome.unrecognised_count,
                    outcome.unrecognised_sample,
                    f"{prefix}/{item.name}",
                )
        elif kind == _DIR:
            walk_subagents(item, f"{prefix}/{item.name}", outcome, cache)


def discover_corpus_detailed(
    corpus_root: Path, cache: Optional[DirListingCache] = None,
) -> DiscoveryOutcome:
    outcome = DiscoveryOutcome()
    corpus_root = Path(corpus_root)
    if not corpus_root.is_dir():
        return outcome

    top = _iter_dir(corpus_root, outcome, cache)
    if top is None:
        return outcome
    for slug_dir, slug_kind in top:
        if slug_kind != _DIR:
            continue
        slug = slug_dir.name
        listing = _iter_dir(slug_dir, outcome, cache)
        if listing is None:
            continue
        for item, kind in listing:
            if kind == _FILE:
                if item.suffix == ".jsonl":
                    outcome.entries.append(
                        CorpusEntry(
                            abs_path=item,
                            source_path=f"{slug}/{item.name}",
                            kind="session",
                        )
                    )
                else:
                    outcome.unrecognised_count = _note(
                        outcome.unrecognised_count,
                        outcome.unrecognised_sample,
                        f"{slug}/{item.name}",
                    )
            elif kind == _DIR:
                sub = item / SUBAGENTS_DIRNAME
                if not sub.is_dir():
                    outcome.unrecognised_count = _note(
                        outcome.unrecognised_count,
                        outcome.unrecognised_sample,
                        f"{slug}/{item.name}",
                    )
                    continue
                walk_subagents(
                    sub, f"{slug}/{item.name}/{SUBAGENTS_DIRNAME}", outcome, cache,
                )
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
