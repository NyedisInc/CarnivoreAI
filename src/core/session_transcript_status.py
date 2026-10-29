"""What a HOOKLESS session's transcript says about it right now.

THE RUNGS, IN ORDER. Newest evidence first, the same ordering
``classify_tail_records`` and ``session_startup_gate`` both use.

  1. MTIME INSIDE THE HEARTBEAT WINDOW -> ``working``. The file was
     appended to within the last :data:`WORKING_HEARTBEAT_TIMEOUT_SECONDS`
     seconds, which is a measurement of NOW and outranks every record of
     THEN. It carries ``expires_at`` so a cached reading cannot outlive
     the window it was taken in.
  2. A TURN END NEWER THAN THE ONE THIS LADDER ALREADY RECORDED ->
     ``finished_unread``, and the AUTO unread flag is claimed ONCE for
     that turn. This is the hookless stand-in for a ``Stop`` hook.
  3. A TURN END ALREADY RECORDED -> ``finished_unread`` while the unread
     flag is still set, ``idle`` once a view has cleared it. Rung 3 is
     what makes a view mean something on a hookless session.
  4. IN FLIGHT OR NOTHING DECIDABLE, WITH A STALE MTIME -> nothing. The
     conversation was mid-turn when the file was last written and that
     was more than a heartbeat ago, so neither rest nor work can be
     claimed. The caller keeps ``unknown``, which is a real answer.
  5. NO TRANSCRIPT, OR ONE THAT COULD NOT BE READ -> nothing, and the two
     are named separately because only the first is a measurement.

A bare shell never reaches any of this: ``resolve_pane_status`` maps a
known shell command straight to ``idle`` and the seam is consulted only
while the answer is still ``unknown``.

A TURN END WITH NO READABLE TIMESTAMP IS NEVER CLAIMED, because there is
no key to make the claim idempotent on. It falls to rung 3, which paints
correctly and writes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from src.core.session_activity import WORKING_HEARTBEAT_TIMEOUT_SECONDS
from src.core.session_status import (
    STATUS_FINISHED_UNREAD,
    STATUS_IDLE,
    STATUS_WORKING,
    derive_read_state,
)
from src.core.session_status_seed_records import TranscriptRest

_HEARTBEAT = timedelta(seconds=WORKING_HEARTBEAT_TIMEOUT_SECONDS)


RUNG_MTIME: str = "mtime"

RUNG_TURN_END_NEW: str = "turn_end_new"

RUNG_TURN_END_SEEN: str = "turn_end_seen"

RUNG_STALE_IN_FLIGHT: str = "stale_in_flight"

# could not be read
RUNG_NO_TRANSCRIPT: str = "no_transcript"


@dataclass(frozen=True)
class TranscriptStatus:

    state: Optional[str] = None
    at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    claim_turn_end_at: Optional[datetime] = None
    rung: str = RUNG_NO_TRANSCRIPT
    detail: str = ""

    @property
    def answers(self) -> bool:
        return bool(self.state)


def mtime_is_fresh(
    mtime: Optional[datetime], now: datetime
) -> bool:
    if mtime is None:
        return False
    age = now - mtime
    return timedelta(0) <= age <= _HEARTBEAT


def resolve_transcript_status(
    *,
    mtime: Optional[datetime],
    tail: Optional[TranscriptRest],
    last_turn_end_seen: Optional[datetime],
    unread: bool,
    now: datetime,
) -> TranscriptStatus:
    if mtime_is_fresh(mtime, now):
        return TranscriptStatus(
            state=STATUS_WORKING,
            at=mtime,
            expires_at=(mtime or now) + _HEARTBEAT,
            rung=RUNG_MTIME,
            detail=(
                "the conversation transcript was appended to within the "
                "last "
                f"{WORKING_HEARTBEAT_TIMEOUT_SECONDS} seconds, which is a "
                "measurement of now and expires like one"
            ),
        )

    if tail is None or not tail.at_rest:
        if tail is None:
            return TranscriptStatus(
                rung=RUNG_NO_TRANSCRIPT,
                detail=(
                    "no transcript was read for this session, so nothing "
                    "about it was measured"
                ),
            )
        return TranscriptStatus(
            rung=RUNG_STALE_IN_FLIGHT,
            detail=(
                "the transcript said "
                f"{tail.verdict} and its file has not been touched inside "
                "the heartbeat window, so neither work nor rest can be "
                "claimed"
            ),
        )

    at = tail.at
    if at is not None and last_turn_end_seen is not None and at > last_turn_end_seen:
        return TranscriptStatus(
            state=STATUS_FINISHED_UNREAD,
            at=at,
            claim_turn_end_at=at,
            rung=RUNG_TURN_END_NEW,
            detail=(
                "the transcript's newest turn end is newer than the one "
                "already recorded for this pane, so this conversation "
                "finished a turn nobody has looked at"
            ),
        )

    return TranscriptStatus(
        state=derive_read_state(STATUS_IDLE, unread=unread),
        at=at,
        rung=RUNG_TURN_END_SEEN,
        detail=(
            "the transcript's newest turn end is one this ladder has "
            "already recorded, so the session is at rest and its unread "
            "flag is whatever a view last left it"
        ),
    )
