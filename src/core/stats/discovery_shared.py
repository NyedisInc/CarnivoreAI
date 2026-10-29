
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Iterable

from src.core.codex_corpus_discover import discover_codex_detailed
from src.core.transcript_corpus_discover import DiscoveryOutcome, discover_corpus_detailed

_TTL_SECONDS = 30
_LOCK = threading.RLock()
_CACHE: dict[tuple[str, str], tuple[float, DiscoveryOutcome]] = {}


def shared_discovery(provider: str, root: Path, *, fresh: bool = False) -> DiscoveryOutcome:
    if provider not in ("claude", "codex"):
        raise ValueError("unsupported provider")
    path = Path(root).expanduser().resolve()
    key = (provider, str(path))
    with _LOCK:
        cached = _CACHE.get(key)
        if not fresh and cached and time.monotonic() - cached[0] < _TTL_SECONDS:
            return cached[1]
        outcome = (discover_corpus_detailed(path) if provider == "claude"
                   else discover_codex_detailed(path))
        if outcome.unreadable_count == 0:
            _CACHE[key] = (time.monotonic(), outcome)
        else:
            _CACHE.pop(key, None)
        return outcome


def merged_claude_discovery(roots: Iterable[Path], *, fresh: bool = False) -> DiscoveryOutcome:
    merged = DiscoveryOutcome()
    seen: set[str] = set()
    for root in roots:
        outcome = shared_discovery("claude", root, fresh=fresh)
        for entry in outcome.entries:
            if entry.source_path in seen:
                continue
            seen.add(entry.source_path)
            merged.entries.append(entry)
        merged.unrecognised_count += outcome.unrecognised_count
        merged.unrecognised_sample.extend(outcome.unrecognised_sample)
        merged.unreadable_count += outcome.unreadable_count
        merged.unreadable_sample.extend(outcome.unreadable_sample)
    del merged.unrecognised_sample[20:]
    del merged.unreadable_sample[20:]
    return merged
