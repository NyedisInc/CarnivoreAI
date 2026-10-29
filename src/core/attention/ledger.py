"""The edge detector: which verdicts are NEWS, and which are the weather.

FIVE RULES, AND EVERY ONE OF THEM EXISTS BECAUSE OF A MEASURED DEFECT.

**FIRST SIGHT OF COMPLETED WORK IS A BASELINE.** An initial busy or done
observation records and returns no transition. An outstanding blocking
prompt still alerts once after its required confirmation. This is what stops the restart toast storm: on
boot the app re-adopts every surviving session and reads each one for the
first time, and a dozen sessions that have been sitting finished since
last night are not a dozen new pieces of news. The state was already true
before we looked.

**A SETTLE-REQUIRED VERDICT MUST BE SEEN TWICE.** The pane and the
end-of-transcript shape are both read mid-render: ``capture-pane`` can
catch a dialog half-drawn, and the transcript's own turn-end record lands
25 ms after the model stops and 7 ms before claude updates its status, so
a single read inside that gap is a read before the source settled. A
verdict the resolver marked :attr:`~AttentionVerdict.settle_required`
must therefore be observed twice, at least :data:`SETTLE_SECONDS` apart,
and a DIFFERENT verdict arriving in between resets the settle.

**``done_idle`` ALSO NEEDS QUIET.** A turn end followed immediately by
another append is not a finished turn, it is the gap between two records.
The caller passes the transcript's newest append time; the ledger holds
the transition until :data:`DONE_QUIET_SECONDS` have passed since it. THE
LEDGER READS NO FILES: the timestamp is an argument, which is what lets
the replay suite drive years of history in milliseconds.

**A FLICKER THROUGH ``unknown`` FREEZES THE ENTRY.** ``unknown`` is a
failure to observe, not an observation of a different state, so it
changes nothing at all: not the confirmed verdict, not a settle in
progress, not the emitted set. Without this, a session that answered
``busy``, then ``unknown`` for one tick because a file was being
rewritten, then ``busy`` again, would produce a second ``busy`` edge out
of nothing. The way back must not manufacture an edge.

**ONE EDGE PER (key, state, reason) UNTIL THE STATE MOVES.** A session
that sits in ``needs_user(permission)`` for ten minutes is one ask, not
three hundred. The emitted set is cleared the moment the STATE changes to
something else, so the same ask after a real detour is news again. A
reason change inside one state IS news, on purpose: ``needs_user`` going
from ``input`` to ``permission`` is a different question for the user.

IT ALSO HOLDS TWO EVIDENCE BASELINES, and :meth:`note_transcript` is
where they live: the newest user prompt and the newest append this key
has already been shown. They are not verdicts, but they are memory, and
putting them anywhere else would give the package a second thing that
remembers. They are what the watcher's side-effect layer reads instead of
a ``UserPromptSubmit`` hook.

KEYED ON THE INSTANCE, NOT THE SESSION ID. The key is
``UnreadStore.compose_key(tmux_name, epoch)``, the same identity the
unread flag already uses, for two reasons the project has already paid
for. Gotcha 4b: a session id is not a tmux name and deriving one from
the other loses sessions. Gotcha 10: ``CLOUDECODE_SESSION_ID`` is fixed
into a pane at spawn, so after a re-adopt the row id and the id the pane
believes in can diverge, and a flag keyed on the row id is one the pane's
own agent can never clear. The tmux name plus ``#{session_created}``
cannot diverge from the pane, because it IS the pane.
"""

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

        # SETTLE_SECONDS
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
