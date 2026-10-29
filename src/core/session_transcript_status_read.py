
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
from src.core.sessions.host_port import SessionHost

_TURN_END_RUNGS: frozenset[str] = frozenset(
    {RUNG_TURN_END_NEW, RUNG_TURN_END_SEEN}
)

logger = structlog.get_logger(__name__)

_READ_ERRORS: Tuple[type, ...] = (sqlite3.Error, OSError, ValueError, KeyError)


@dataclass(frozen=True)
class TranscriptReading:

    mtime: Optional[datetime]
    tail: TranscriptRest


def read_transcript_signal(
    uuid: Optional[str],
    working_dir: Optional[str],
    *,
    session_id: Optional[str] = None,
) -> TranscriptReading:
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


def ledger_for(manager: SessionHost) -> TranscriptTurnLedger:
    try:
        held = _LEDGERS.get(manager)
        if held is None:
            held = TranscriptTurnLedger()
            _LEDGERS[manager] = held
        return held
    except TypeError:
        return TranscriptTurnLedger()


def transcript_status_for(
    manager: SessionHost,
    *,
    session_id: str,
    tmux_name: Optional[str],
    epoch: Optional[int],
    reading: Optional[TranscriptReading],
    unread: bool,
    now: datetime,
) -> TranscriptStatus:
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
    manager: SessionHost,
    session_id: str,
    tmux_name: Optional[str],
    epoch: Optional[int],
) -> None:
    if not tmux_name:
        return
    store = manager._unread_store
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
