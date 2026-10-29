
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.core.session_status import (
    STATUS_IDLE,
    derive_read_state,
)

from src.core.session_status_seed_records import (  # noqa: F401
    IN_FLIGHT_STOP_REASONS,
    LOCAL_COMMAND_MARKERS,
    LOCAL_COMMAND_SUBTYPE,
    REST_STOP_REASONS,
    REST_SYSTEM_SUBTYPES,
    TAIL_ABSENT,
    TAIL_AT_REST,
    TAIL_IN_FLIGHT,
    TAIL_NO_MARKER,
    TAIL_UNREADABLE,
    TranscriptRest,
    classify_record,
    classify_tail_records,
    is_local_command_envelope,
    parse_timestamp,
)


SEED_REFRESH_INTERVAL_SECONDS: int = 60


SEED_RUNG_ROW: str = "row"

SEED_RUNG_TRANSCRIPT: str = "transcript"

SEED_RUNG_NONE: str = "none"

@dataclass(frozen=True)
class StatusSeed:

    state: Optional[str] = None
    at: Optional[datetime] = None
    rung: str = SEED_RUNG_NONE
    detail: Optional[str] = None
    expires_at: Optional[datetime] = None

    @property
    def seeds(self) -> bool:
        return bool(self.state)


def resolve_status_seed(
    *,
    row_state: Optional[str],
    row_state_at: Optional[str],
    tail: Optional[TranscriptRest] = None,
    live: Optional["TranscriptStatus"] = None,
    now: Optional[datetime] = None,
) -> StatusSeed:
    from src.core.activity_persist import restore_state

    if live is not None and live.answers:
        return StatusSeed(
            state=live.state,
            at=live.at,
            rung=SEED_RUNG_TRANSCRIPT,
            detail=live.detail,
            expires_at=live.expires_at,
        )

    restored, reason = restore_state(row_state, row_state_at, now=now)
    if restored:
        return StatusSeed(
            state=restored,
            at=parse_timestamp(row_state_at),
            rung=SEED_RUNG_ROW,
            detail=(
                f"the session's own instance row records {restored!r} and "
                "that record is still worth something"
            ),
        )

    if tail is None:
        return StatusSeed(
            rung=SEED_RUNG_NONE,
            detail=(
                f"the row answered nothing ({reason}) and the transcript "
                "was not consulted"
            ),
        )

    if tail.at_rest:
        return StatusSeed(
            state=STATUS_IDLE,
            at=tail.at,
            rung=SEED_RUNG_TRANSCRIPT,
            detail=tail.detail,
        )

    return StatusSeed(
        rung=SEED_RUNG_NONE,
        detail=(
            f"the row answered nothing ({reason}) and the transcript said "
            f"{tail.verdict}"
        ),
    )


def display_state(
    seed: StatusSeed,
    *,
    unread: bool = False,
    now: Optional[datetime] = None,
) -> Optional[str]:
    if not seed.seeds:
        return None
    if seed.expires_at is not None:
        stamp = now or datetime.now(timezone.utc)
        if stamp > seed.expires_at:
            return None
    return derive_read_state(seed.state, unread=unread)
