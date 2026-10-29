
from __future__ import annotations

import glob
import os
from datetime import datetime
from typing import Optional

import structlog

from src.core.attention.codex_reader import (
    CodexEvidence,
    CodexRecordFacts,
    CodexTranscriptFacts,
)
from src.core.attention.codex_stores import (
    _connect_ro,
    latest_history_db,
    read_codex_record,
    read_codex_transcript,
    writer_lock_live,
)

logger = structlog.get_logger()

DEFAULT_CODEX_HOME = os.path.expanduser("~/.codex")


def _latest_state_db(codex_home: str) -> Optional[str]:
    matches = glob.glob(os.path.join(codex_home, "state_*.sqlite"))
    return sorted(matches)[-1] if matches else None


def rollout_path_for(codex_home: str, thread_uuid: str) -> Optional[str]:
    state_db = _latest_state_db(codex_home)
    if state_db is not None:
        con = _connect_ro(state_db)
        if con is not None:
            try:
                row = con.execute(
                    "SELECT rollout_path FROM threads WHERE id = ?",
                    (thread_uuid,),
                ).fetchone()
                if row is not None and row[0]:
                    return os.path.expanduser(str(row[0]))
            except Exception:  # noqa: BLE001
                pass
            finally:
                con.close()
    return rollout_path_in_sessions(codex_home, thread_uuid)


def rollout_path_in_sessions(codex_home: str, thread_uuid: str) -> Optional[str]:
    hits = glob.glob(
        os.path.join(
            codex_home, "sessions", "*", "*", "*",
            "rollout-*-%s.jsonl" % thread_uuid,
        )
    )
    return sorted(hits)[-1] if hits else None


def gather_codex_evidence(
    thread_uuid: Optional[str],
    *,
    codex_home: Optional[str] = None,
    now: datetime,
) -> Optional[CodexEvidence]:
    if not thread_uuid:
        return None
    home = codex_home or DEFAULT_CODEX_HOME
    try:
        rollout_path = rollout_path_for(home, thread_uuid)
        rollout_size = None
        if rollout_path is not None:
            try:
                rollout_size = os.path.getsize(rollout_path)
            except OSError:
                rollout_size = None
        db = latest_history_db(home)
        lock_live = writer_lock_live(home, thread_uuid)
        record = (
            read_codex_record(
                db, thread_uuid, lock_live=lock_live, rollout_size=rollout_size
            )
            if db is not None
            else CodexRecordFacts()
        )
        transcript = (
            read_codex_transcript(rollout_path, now=now)
            if rollout_path is not None
            else CodexTranscriptFacts(
                readable=False, detail="no codex rollout path resolved"
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("codex_gather_failed", uuid=thread_uuid, error=str(exc))
        return CodexEvidence(detail="codex gather failed: %s" % exc)
    return CodexEvidence(
        record=record,
        transcript=transcript,
        pane=None,
        detail="codex evidence gathered from %s" % home,
    )
