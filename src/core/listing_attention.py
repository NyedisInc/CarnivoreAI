
from __future__ import annotations

import os
import threading
from datetime import datetime
from typing import Any, Dict, Mapping, Optional, Tuple

import structlog

from src.core.attention import registry_index
from src.core.attention.absent_transcript_cache import ABSENT_TRANSCRIPTS
from src.core.attention.display import (
    activity_hint_for,
    status_source_for,
    to_display,
)
from src.core.attention.evidence import FAMILY_CODEX, Evidence, PaneVerdict
from src.core.attention.process_scope import evidence_process_floor
from src.core.attention.registry_record import RegistryRecord
from src.core.attention.registry_index import registry_for_session
from src.core.attention.registry_pane import (
    ProcessParents,
    falls_back_to_pane,
    registry_for_pane,
)
from src.core.attention.resolve import resolve_attention
from src.core.attention.transcript_facts import (
    FACTS_UNREADABLE,
    TranscriptFacts,
    read_transcript_facts,
)

logger = structlog.get_logger()

_READ_ERRORS = (OSError, ValueError)

_PROGRAMMING_ERRORS = (TypeError, AttributeError, KeyError)

_FACTS_MEMO: Dict[str, Tuple[int, int, TranscriptFacts]] = {}

_FACTS_MEMO_LOCK = threading.Lock()

FACTS_MEMO_MAX_ENTRIES: int = 256


def transcript_facts_for(
    claude_session_uuid: Optional[str],
    working_dir: Optional[str],
    *,
    now: Optional[datetime] = None,
) -> TranscriptFacts:
    if not claude_session_uuid:
        return TranscriptFacts(
            verdict=FACTS_UNREADABLE,
            detail=(
                "no claude conversation is bound to this row, so there is "
                "no transcript to read attention out of"
            ),
        )
    try:
        from src.core.session_token_usage.claude_reader import locate_transcript
        from src.core.session_transcript_presence import CONVERSATION_ABSENT

        presence = locate_transcript(
            str(claude_session_uuid), working_dir=working_dir
        )
    except _READ_ERRORS as exc:
        logger.warning(
            "listing_attention_presence_failed",
            uuid=str(claude_session_uuid),
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return TranscriptFacts(
            verdict=FACTS_UNREADABLE,
            detail="the transcript could not be located: %s" % exc,
        )
    except _PROGRAMMING_ERRORS as exc:
        logger.error(
            "listing_attention_presence_bug",
            uuid=str(claude_session_uuid),
            error=str(exc),
            error_type=type(exc).__name__,
            exc_info=True,
        )
        return TranscriptFacts(
            verdict=FACTS_UNREADABLE,
            detail="the transcript could not be located: %s" % exc,
        )

    if presence.path is None:
        return TranscriptFacts(
            verdict=FACTS_UNREADABLE,
            detail=presence.detail or "no transcript file was found",
            absent=presence.outcome == CONVERSATION_ABSENT,
        )
    return _facts_for_path(str(presence.path), now=now)


def _facts_for_path(
    path: str, *, now: Optional[datetime] = None
) -> TranscriptFacts:
    try:
        stat = os.stat(path)
        key = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return read_transcript_facts(path, now=now)

    with _FACTS_MEMO_LOCK:
        cached = _FACTS_MEMO.get(path)
    if cached is not None and (cached[0], cached[1]) == key:
        return cached[2]

    facts = read_transcript_facts(path, now=now)
    with _FACTS_MEMO_LOCK:
        if len(_FACTS_MEMO) >= FACTS_MEMO_MAX_ENTRIES:
            _FACTS_MEMO.clear()
        _FACTS_MEMO[path] = (key[0], key[1], facts)
    return facts


def attention_reads_for_name(
    tmux_name: Optional[str],
    *,
    registry_index: Optional[Mapping[str, RegistryRecord]],
    session_started_epoch: Optional[int],
    claude_session_uuid: Optional[str],
    working_dir: Optional[str],
    now: Optional[datetime] = None,
    transcript_reader: Optional[Any] = None,
    pane_id: Optional[str] = None,
    pane_pid: Optional[int] = None,
    process_parents: Optional[ProcessParents] = None,
    process_floor_at: Optional[datetime] = None,
) -> Tuple[RegistryRecord, TranscriptFacts]:
    registry = registry_for_session(
        tmux_name=tmux_name,
        index=registry_index if registry_index is not None else {},
        session_started_epoch=session_started_epoch,
        claude_session_uuid=claude_session_uuid,
        process_floor_at=process_floor_at,
    )
    if falls_back_to_pane(registry):
        registry = registry_for_pane(
            index=registry_index if registry_index is not None else {},
            pane_id=pane_id,
            pane_pid=pane_pid,
            process_parents=process_parents,
            session_started_epoch=session_started_epoch,
            claude_session_uuid=claude_session_uuid,
            process_floor_at=process_floor_at,
        ) or registry
    reader = transcript_reader or transcript_facts_for
    transcript = ABSENT_TRANSCRIPTS.recall(
        claude_session_uuid, session_started_epoch, registry, working_dir
    )
    if transcript is None:
        transcript = reader(claude_session_uuid, working_dir, now=now)
        ABSENT_TRANSCRIPTS.remember(
            claude_session_uuid, session_started_epoch, registry, working_dir,
            transcript,
        )
    return (registry, transcript)


def resolve_row_status(
    *,
    registry: RegistryRecord,
    transcript: TranscriptFacts,
    tmux_liveness: str,
    agent_family: Optional[str],
    pane: Optional[PaneVerdict],
    unread: bool,
    tmux_status: str,
    now: datetime,
    codex: Optional[Any] = None,
    resting_prompt_held: bool = False,
    process_floor_at: Optional[datetime] = None,
) -> Tuple[str, str, Optional[str]]:
    verdict = resolve_attention(
        Evidence(
            tmux_liveness=tmux_liveness,
            agent_family=agent_family,
            registry=registry,
            transcript=transcript,
            pane=pane,
            now=now,
            codex=codex,
            resting_prompt_held=resting_prompt_held,
            process_floor_at=process_floor_at,
        )
    )
    return (
        to_display(verdict, unread=unread, tmux_status=tmux_status),
        status_source_for(verdict),
        verdict.activity_hint or activity_hint_for(registry),
    )


def resolve_row_status_live(
    *,
    tmux_name: Optional[str],
    epoch: Optional[int],
    index: Optional[Any],
    family: Optional[str],
    liveness: str,
    unread: bool,
    tmux_status: str,
    working_dir: Optional[str],
    now: datetime,
    restarted_at: Optional[datetime] = None,
) -> Tuple[str, str, Optional[str]]:
    uuid, row_cwd = conversation_for_instance(index, tmux_name, epoch)
    is_codex = family == FAMILY_CODEX
    registry, transcript = attention_reads_for_name(
        tmux_name,
        registry_index=registry_index.read_registry_index(),
        session_started_epoch=epoch,
        claude_session_uuid=None if is_codex else uuid,
        working_dir=row_cwd or working_dir,
        now=now,
        process_floor_at=restarted_at,
    )
    codex = None
    if is_codex:
        from src.core.attention.codex_gather import (
            DEFAULT_CODEX_HOME,
            gather_codex_evidence,
        )
        from src.core.attention.codex_reader import CodexEvidence

        codex = gather_codex_evidence(
            uuid, codex_home=DEFAULT_CODEX_HOME, now=now
        ) or CodexEvidence()
    return resolve_row_status(
        registry=registry,
        transcript=transcript,
        tmux_liveness=liveness,
        agent_family=family,
        pane=None,
        unread=unread,
        tmux_status=tmux_status,
        now=now,
        codex=codex,
        process_floor_at=evidence_process_floor(epoch, restarted_at),
    )


def conversation_for_instance(
    index: Any, tmux_name: Optional[str], epoch: Optional[int]
) -> Tuple[Optional[str], Optional[str]]:
    if index is None or not getattr(index, "complete", False):
        return (None, None)
    reader = getattr(index, "seed_row", None)
    if not callable(reader):
        return (None, None)
    try:
        row = reader(tmux_name, epoch)
    except _READ_ERRORS:
        return (None, None)
    except _PROGRAMMING_ERRORS as exc:
        logger.error("listing_attention_seed_row_bug", error_type=type(exc).__name__, exc_info=True)
        return (None, None)
    if not row:
        return (None, None)
    return (row.get("claude_session_uuid"), row.get("working_dir"))
