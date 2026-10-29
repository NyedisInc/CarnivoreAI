
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from weakref import WeakKeyDictionary

import structlog

from src.core.session_status_seed_records import (
    TAIL_ABSENT,
    TAIL_UNREADABLE,
    TranscriptRest,
    classify_tail_records,
)
from src.core.session_transcript_status import (
    RUNG_TURN_END_NEW,
    RUNG_TURN_END_SEEN,
    TranscriptStatus,
    resolve_transcript_status,
)
from src.core.unread_store import UnreadStore

_TURN_END_RUNGS: frozenset[str] = frozenset(
    {RUNG_TURN_END_NEW, RUNG_TURN_END_SEEN}
)

logger = structlog.get_logger(__name__)

_READ_ERRORS: Tuple[type, ...] = (sqlite3.Error, OSError, ValueError, KeyError)


@dataclass(frozen=True)
class TranscriptReading:
    """One transcript, read once: when it was last written, and what it says.

    Description: the return of :func:`read_transcript_signal`. Both
      halves come off a SINGLE presence resolution, which is the whole
      reason this type exists rather than two functions - resolving the
      path twice per poll would double the only I/O on this path.

      - ``mtime``: the file's modification time, timezone-aware, or None
        when there is no file or it could not be stat'ed.
      - ``tail``: what the last decidable record says, never None.
    Inputs: n/a.
    Output: n/a (data holder).
    """

    mtime: Optional[datetime]
    tail: TranscriptRest


def read_transcript_signal(
    uuid: Optional[str],
    working_dir: Optional[str],
    *,
    session_id: Optional[str] = None,
) -> TranscriptReading:
    """Read one conversation's transcript mtime and tail verdict, once.

    Description: resolves the uuid to a file through
      ``conversation_presence`` and then takes BOTH measurements off that
      one path. THREE REFUSALS, kept apart: no uuid bound to the row, a
      MEASURED absent transcript, and a file that could not be read.
      None of them is evidence of rest, and only the middle one is
      evidence of anything. Never raises.
    Inputs: uuid (str | None) - ``sessions.claude_session_uuid``.
      working_dir (str | None) - used only for the fast-path slug.
      session_id (str | None) - for the failure log only.
    Output: TranscriptReading.
    Example: read_transcript_signal(uuid, '/Users/x/proj').tail.verdict
    """
    if not uuid:
        return TranscriptReading(
            mtime=None,
            tail=TranscriptRest(
                TAIL_ABSENT,
                detail=(
                    "no claude conversation is bound to this row, so there "
                    "is no transcript to read a status out of"
                ),
            ),
        )

    try:
        from src.core.session_transcript_presence import (
            STATUS_CACHE_SECONDS,
            conversation_presence,
        )

        presence = conversation_presence(
            str(uuid), working_dir=working_dir, cache_seconds=STATUS_CACHE_SECONDS
        )
    except _READ_ERRORS as exc:
        logger.warning(
            "transcript_status_presence_failed",
            session_id=session_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return TranscriptReading(
            mtime=None,
            tail=TranscriptRest(
                TAIL_UNREADABLE,
                detail=f"the transcript could not be located: {exc}",
            ),
        )

    if presence.path is None:
        return TranscriptReading(
            mtime=None,
            tail=TranscriptRest(
                TAIL_ABSENT if presence.missing else TAIL_UNREADABLE,
                detail=presence.detail,
            ),
        )

    mtime: Optional[datetime] = None
    try:
        stamp = presence.path.stat().st_mtime
        mtime = datetime.fromtimestamp(stamp, tz=timezone.utc)
    except _READ_ERRORS as exc:
        logger.warning(
            "transcript_status_stat_failed",
            session_id=session_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )

    from src.core.claude_title_sync import read_tail_records

    read = read_tail_records(str(presence.path))
    if not read.readable:
        return TranscriptReading(
            mtime=mtime,
            tail=TranscriptRest(TAIL_UNREADABLE, detail=read.detail),
        )
    return TranscriptReading(mtime=mtime, tail=classify_tail_records(read.records))


class TranscriptTurnLedger:

    def __init__(self) -> None:
        self._seen: Dict[str, datetime] = {}

    def newest_seen(self, key: str) -> Optional[datetime]:
        return self._seen.get(key)

    def observe(self, key: str, at: Optional[datetime]) -> bool:
        """Record a turn end and say whether it was NEWER than what we held.

        Description: False on a first sighting (the baseline rule above),
          False for an older or equal timestamp, and False for a
          timestamp that could not be read - there is no key to make a
          claim idempotent on, so no claim is made. True ONLY for a
          strictly newer turn end on an instance already being watched.

          THE BASELINE ONLY EVER MOVES FORWARD. An older reading does
          not rewind it, because rewinding would let the next ordinary
          poll see the newer turn end again and claim it a second time -
          the duplicate this whole class exists to prevent. Readings can
          go backwards for real reasons: a tail window that a large tool
          result pushed the newer marker out of, or a transcript rolled
          over. Neither is evidence that a turn un-happened.
        Inputs: key (str) - ``<tmux_name>@<epoch>``. at (datetime | None)
          - the turn end's timestamp.
        Output: bool - True means the caller owes exactly one unread
          claim for this turn.
        Example: ledger.observe('cloude_x@1', later) -> True
        """
        if not key or at is None:
            return False
        previous = self._seen.get(key)
        if previous is None:
            self._seen[key] = at
            return False
        if at > previous:
            self._seen[key] = at
            return True
        return False

    def forget(self, key: str) -> None:
        self._seen.pop(key, None)


_LEDGERS: "WeakKeyDictionary[Any, TranscriptTurnLedger]" = WeakKeyDictionary()


def ledger_for(manager: Any) -> TranscriptTurnLedger:
    try:
        held = _LEDGERS.get(manager)
        if held is None:
            held = TranscriptTurnLedger()
            _LEDGERS[manager] = held
        return held
    except TypeError:
        return TranscriptTurnLedger()


def transcript_status_for(
    manager: Any,
    *,
    session_id: str,
    tmux_name: Optional[str],
    epoch: Optional[int],
    reading: Optional[TranscriptReading],
    unread: bool,
    now: datetime,
) -> TranscriptStatus:
    """Apply the hookless transcript ladder, and claim one unread if owed.

    Description: THE SEAM. Runs the PURE ladder against the reading, then
      does the one thing the ladder is not allowed to do - record the
      turn end and set the AUTO unread flag, exactly once per newly-seen
      turn, through the same ``UnreadStore`` the ``Stop`` hook writes.
      Never raises: a failed write costs an unread badge, and must never
      cost the listing.

      THE ORDER MATTERS. The ledger is consulted BEFORE it is updated,
      because the pure ladder needs to be told what was already known;
      updating first would make every turn end look already-seen and the
      unread claim would never fire at all.
    Inputs: manager (SessionManager) - for the unread store only.
      session_id (str) - for logs. tmux_name (str | None) and epoch
      (int | None) - the instance the ledger and the flag key on.
      reading (TranscriptReading | None). unread (bool) - the persisted
      flag as it stands. now (datetime) - tz-aware clock.
    Output: TranscriptStatus - ``answers`` is False when no rung
      answered.
    Example:
      transcript_status_for(mgr, session_id=sid, tmux_name=n, epoch=e,
                            reading=r, unread=False, now=now).state
    """
    key = UnreadStore.compose_key(tmux_name, epoch) if tmux_name else ""
    ledger = ledger_for(manager)
    status = resolve_transcript_status(
        mtime=reading.mtime if reading else None,
        tail=reading.tail if reading else None,
        last_turn_end_seen=ledger.newest_seen(key) if key else None,
        unread=unread,
        now=now,
    )

    if key and status.rung in _TURN_END_RUNGS and status.at is not None:
        is_new = ledger.observe(key, status.at)
        if is_new and status.claim_turn_end_at is not None:
            _claim_unread(manager, session_id, tmux_name, epoch)
    return status


def _claim_unread(
    manager: Any,
    session_id: str,
    tmux_name: Optional[str],
    epoch: Optional[int],
) -> None:
    if not tmux_name:
        return
    store = getattr(manager, "_unread_store", None)
    if store is None:
        return
    try:
        store.set_flag(tmux_name, "auto", True, epoch=epoch)
        logger.info(
            "transcript_turn_end_marked_unread",
            session_id=session_id,
            tmux_name=tmux_name,
        )
    except _READ_ERRORS as exc:
        logger.warning(
            "transcript_unread_claim_failed",
            session_id=session_id,
            tmux_name=tmux_name,
            error=str(exc),
            error_type=type(exc).__name__,
        )
