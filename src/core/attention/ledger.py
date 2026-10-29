
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Set, Tuple

from src.core.attention.evidence import AttentionVerdict, STATE_DONE_IDLE, STATE_NEEDS_USER, STATE_UNKNOWN
from src.core.attention.resolve import DONE_QUIET_SECONDS, SETTLE_SECONDS


@dataclass(frozen=True)
class Transition:

    key: str

    state: str

    reason: str

    verdict: AttentionVerdict

    previous_state: Optional[str]

    at: datetime


@dataclass
class _Entry:

    confirmed_state: Optional[str] = None

    confirmed_reason: Optional[str] = None

    candidate: Optional[Tuple[str, str]] = None

    candidate_since: Optional[datetime] = None

    emitted: Set[Tuple[str, str]] = field(default_factory=set)

    seen_user_prompt_at: Optional[datetime] = None
    seen_append_at: Optional[datetime] = None

    evidence_noted: bool = False


def _elapsed(now: datetime, since: Optional[datetime]) -> Optional[float]:
    if since is None:
        return None
    try:
        return (now - since).total_seconds()
    except TypeError:
        return None


def _is_newer(candidate: Optional[datetime], seen: Optional[datetime]) -> bool:
    if candidate is None:
        return False
    if seen is None:
        return True
    try:
        return candidate > seen
    except TypeError:
        return False


class AttentionLedger:

    def __init__(self) -> None:
        self._entries: Dict[str, _Entry] = {}

    def observe(
        self,
        key: str,
        verdict: AttentionVerdict,
        now: datetime,
        *,
        last_append_at: Optional[datetime] = None,
    ) -> Optional[Transition]:
        entry = self._entries.get(key)

        if verdict.state == STATE_UNKNOWN:
            if entry is None:
                self._entries[key] = _Entry()
            return None

        if (entry is None or entry.confirmed_state is None) and verdict.state != STATE_NEEDS_USER:
            fresh = entry if entry is not None else _Entry()
            fresh.confirmed_state = verdict.state
            fresh.confirmed_reason = verdict.reason
            fresh.emitted = {(verdict.state, verdict.reason)}
            fresh.candidate = None
            fresh.candidate_since = None
            self._entries[key] = fresh
            return None

        if entry is None:
            entry = _Entry()
            self._entries[key] = entry
        pair = (verdict.state, verdict.reason)

        if verdict.settle_required:
            if entry.candidate != pair:
                entry.candidate = pair
                entry.candidate_since = now
                return None
            waited = _elapsed(now, entry.candidate_since)
            if waited is None or waited < SETTLE_SECONDS:
                return None
        else:
            entry.candidate = None
            entry.candidate_since = None

        if verdict.state == STATE_DONE_IDLE and last_append_at is not None:
            quiet = _elapsed(now, last_append_at)
            if quiet is None or quiet < DONE_QUIET_SECONDS:
                return None

        previous = entry.confirmed_state
        if previous != verdict.state:
            entry.emitted = set()
        entry.confirmed_state = verdict.state
        entry.confirmed_reason = verdict.reason
        if pair in entry.emitted:
            return None
        entry.emitted.add(pair)
        return Transition(
            key=key,
            state=verdict.state,
            reason=verdict.reason,
            verdict=verdict,
            previous_state=previous,
            at=now,
        )

    def note_transcript(
        self,
        key: str,
        *,
        user_prompt_at: Optional[datetime],
        append_at: Optional[datetime],
    ) -> Tuple[Optional[datetime], bool]:
        entry = self._entries.get(key)
        if entry is None:
            entry = _Entry()
            self._entries[key] = entry

        first = not entry.evidence_noted
        entry.evidence_noted = True

        new_prompt: Optional[datetime] = None
        if not first and _is_newer(user_prompt_at, entry.seen_user_prompt_at):
            new_prompt = user_prompt_at
        if _is_newer(user_prompt_at, entry.seen_user_prompt_at):
            entry.seen_user_prompt_at = user_prompt_at

        appended = first or _is_newer(append_at, entry.seen_append_at)
        if _is_newer(append_at, entry.seen_append_at):
            entry.seen_append_at = append_at

        return new_prompt, appended

    def confirmed_state(self, key: str) -> Optional[str]:
        entry = self._entries.get(key)
        return None if entry is None else entry.confirmed_state

    def forget(self, key: str) -> None:
        self._entries.pop(key, None)

    def tracked_keys(self) -> Tuple[str, ...]:
        return tuple(self._entries)
