"""Pick a REAL idle-since for the idle clock's first observation. Pure.

WHY THIS EXISTS. :mod:`idle_clock` measures a run from the observation that
started it, and every server restart starts a fresh :class:`IdleClock` with
no runs in it. A merge restarts the server every 5 to 25 minutes (see the
work skill's "Merging" section), so before this module existed the FIRST
idle observation after any restart reset every session's idle-since to
"now" - a session idle for six hours before the restart looked freshly idle
after it, and could never reach the sleep threshold.

WHAT THIS MODULE DOES NOT DO. It never touches a filesystem, a clock, or a
config file. :func:`pick_idle_seed` is handed already-resolved candidate
timestamps (real mtimes, or a status time a reader already exposed) and
picks the newest one, clamped so the result can never be reported as
starting before this process's own claude/codex process began or after
"now". The actual file-stat and path-resolution work - which registry
directory, which transcript path, which rollout path - lives in
:mod:`src.core.attention_wiring`, right where the attention watcher already
resolves those same paths for its own tiers (``registry``, ``transcript``,
``codex``), so this module never re-derives a resolver that already exists.

WHY A CLAMP AT ALL. Evidence on disk can be OLDER than the process it is
about: a claude registry file from a previous run of the SAME pane, or a
transcript whose last write predates a `--resume`. Reporting a seed from
before this process existed would claim the session was idle before its
own agent started, which cannot be true. The floor is therefore the
current process's own start time when it is known (the claude registry's
own ``startedAt``), or the tmux pane's creation time otherwise - a pane's
process can never have started before the pane that hosts it, so that is
always a safe (if occasionally loose) floor.
"""

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
    """The newest readable candidate, clamped to ``[process_started_at, now]``.

    Description: PURE, TOTAL, NEVER RAISES. ``candidates`` is a list of
      (timestamp or None, source label) pairs; every ``None`` entry is
      dropped before comparing, so a caller may pass in exactly the sources
      its family has (claude passes two, codex passes two, either may pass
      fewer when a path could not be resolved at all) without special-casing
      an absent one. When every candidate is ``None``, or the list is empty,
      the answer is "now" with :data:`SOURCE_FALLBACK_NOW` - the same
      behaviour the clock had before seeding existed, so a session with no
      readable evidence is never worse off than today.
    Inputs:
      now (datetime) - aware UTC, the observation's own timestamp.
      process_started_at (datetime | None) - the floor; None skips that
        clamp entirely (nothing to clamp against).
      candidates (list[tuple[datetime | None, str]]) - every source this
        family can offer, most of them already read.
    Output: SeedResult - never None.
    Example:
      pick_idle_seed(now=t2, process_started_at=None,
                      candidates=[(t0, 'claude_registry_mtime'),
                                  (t1, 'claude_transcript_mtime')])
      # picks t1 if t1 > t0
    """
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
