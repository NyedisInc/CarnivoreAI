
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

SOURCE_CLAUDE_REGISTRY: str = "claude_registry_mtime"
SOURCE_CLAUDE_TRANSCRIPT: str = "claude_transcript_mtime"
SOURCE_CODEX_ROLLOUT: str = "codex_rollout_mtime"
SOURCE_CODEX_STATUS: str = "codex_status_time"
SOURCE_FALLBACK_NOW: str = "fallback_now"

ALL_SOURCES: frozenset = frozenset(
    {
        SOURCE_CLAUDE_REGISTRY,
        SOURCE_CLAUDE_TRANSCRIPT,
        SOURCE_CODEX_ROLLOUT,
        SOURCE_CODEX_STATUS,
        SOURCE_FALLBACK_NOW,
    }
)


@dataclass(frozen=True)
class SeedResult:

    since: datetime
    source: str
    clamped_to_process_start: bool = False
    clamped_to_now: bool = False


def pick_idle_seed(
    *,
    now: datetime,
    process_started_at: Optional[datetime],
    candidates: List[Tuple[Optional[datetime], str]],
) -> SeedResult:
    usable = [(when, source) for when, source in candidates if when is not None]
    if not usable:
        return SeedResult(since=now, source=SOURCE_FALLBACK_NOW)

    when, source = max(usable, key=lambda pair: pair[0])

    clamped_to_now = when > now
    since = min(when, now)

    clamped_to_process_start = (
        process_started_at is not None and since < process_started_at
    )
    if clamped_to_process_start:
        since = min(process_started_at, now)

    return SeedResult(
        since=since,
        source=source,
        clamped_to_process_start=clamped_to_process_start,
        clamped_to_now=clamped_to_now,
    )
