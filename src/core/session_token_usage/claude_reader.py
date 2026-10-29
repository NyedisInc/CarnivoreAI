"""Sum one claude conversation's token usage out of its own transcript.

WHAT IT READS. Claude Code writes one conversation as
``<corpus>/<project-slug>/<uuid>.jsonl``, one JSON object per line. The
lines that carry billing are the ones with ``type == "assistant"``, whose
``message.usage`` object holds the four token classes the API billed:
``input_tokens`` (FRESH input only), ``cache_creation_input_tokens``,
``cache_read_input_tokens`` and ``output_tokens``. Those four are
DISJOINT in claude's convention - the cached tokens are not also counted
in ``input_tokens`` - which is why the sum of all four is the honest
total and why no subtraction happens anywhere in this module.

The de-duplication is a consecutive-run check, not a set of every id
ever seen, and that is a measured decision rather than a shortcut: on
the same transcript, ZERO message ids reappeared after a different id
had intervened. A run check costs one string in memory; a set costs one
entry per message and would have to survive the incremental cache.

THREE OUTCOMES. A transcript that is found and read is ``ok``. A row with
no conversation id, or an id with no file under the corpus, is
``absent`` - nothing has run, so nothing was spent. A corpus we could not
list, or a file we could not open, is ``unchecked``, and it never
collapses into ``absent``: a relocated corpus would otherwise report
every session as having cost nothing.

A MALFORMED LINE IS SKIPPED AND COUNTED, NEVER ZEROED. A transcript
being appended to while we read it ends in a half-written line by
definition, so treating a parse failure as a fatal error would make the
panel fail exactly while a session was busy.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Dict, Optional, Tuple

import structlog

from src.core.claude_project_dirs import candidate_project_dirs
from src.core.session_token_usage.cache import (
    HEAD_BYTES,
    TRANSCRIPT_CACHE,
    IncrementalCache,
    TranscriptTotals,
    coerce_token_count,
    stat_signature,
)
from src.core.session_token_usage.claude_selection import (
    read_selection,
    read_ultra_marker,
)
from src.core.session_transcript_presence import (
    CONVERSATION_ABSENT,
    CONVERSATION_PRESENT,
    CONVERSATION_UNCHECKED,
    conversation_presence,
)

logger = structlog.get_logger()


@dataclass(frozen=True)
class TranscriptLocation:

    outcome: str
    path: Optional[Path] = None
    detail: Optional[str] = None


def _locate_in_root(
    conversation_uuid: Optional[str],
    *,
    working_dir: Optional[str],
    root: Optional[Path],
) -> TranscriptLocation:
    if conversation_uuid:
        for directory in candidate_project_dirs(working_dir, projects_dir=root):
            candidate = directory / f"{conversation_uuid}.jsonl"
            try:
                if candidate.is_file():
                    return TranscriptLocation(CONVERSATION_PRESENT, path=candidate)
            except OSError as exc:
                logger.debug(
                    "token_usage_candidate_unreadable",
                    candidate=str(candidate),
                    error=str(exc),
                )
    presence = conversation_presence(
        conversation_uuid, working_dir=working_dir, corpus_root=root
    )
    return TranscriptLocation(
        presence.outcome, path=presence.path, detail=presence.detail
    )


def locate_transcript(
    conversation_uuid: Optional[str],
    *,
    working_dir: Optional[str] = None,
    projects_dir: Optional[Path] = None,
) -> TranscriptLocation:
    """Find the transcript for a conversation uuid, across every account.

    Description: with an explicit ``projects_dir`` (tests) it searches that
      one root. Without one it searches the default ``~/.claude/projects``
      and then every configured claude account's own ``projects`` directory
      (``claude_config.transcript_roots``), because a pane launched on a
      managed account writes its transcript under ITS config directory
      (issue #1102). First PRESENT wins. Otherwise the default root's answer
      is kept, except that a root that could not be read (UNCHECKED) turns
      an all-absent result into UNCHECKED: "not found" must never be
      claimed over a directory that was not looked at.
    Inputs: conversation_uuid (str | None). working_dir (str | None).
      projects_dir (Path | None) - single-root override.
    Output: TranscriptLocation.
    Example: locate_transcript("deab833f-...", working_dir="/x").outcome
    """
    if projects_dir is not None:
        return _locate_in_root(
            conversation_uuid, working_dir=working_dir, root=projects_dir
        )
    from src.core.claude_config.transcript_roots import claude_transcript_roots

    first: Optional[TranscriptLocation] = None
    unchecked: Optional[TranscriptLocation] = None
    for root in claude_transcript_roots():
        found = _locate_in_root(conversation_uuid, working_dir=working_dir, root=root)
        if found.outcome == CONVERSATION_PRESENT:
            return found
        if first is None:
            first = found
        elif found.outcome != CONVERSATION_ABSENT and unchecked is None:
            unchecked = found
    if first is not None and first.outcome == CONVERSATION_ABSENT and unchecked is not None:
        return unchecked
    return first


def _usage_of(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if record.get("type") != "assistant":
        return None
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    return usage if isinstance(usage, dict) else None


def scan_lines(handle: BinaryIO, totals: TranscriptTotals) -> Tuple[TranscriptTotals, int]:
    offset = handle.tell()
    while True:
        line = handle.readline()
        if not line:
            break
        if not line.endswith(b"\n"):
            break
        offset += len(line)
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except (ValueError, UnicodeDecodeError):
            totals = totals.plus_malformed()
            continue
        if not isinstance(record, dict):
            totals = totals.plus_malformed()
            continue
        ultra = read_ultra_marker(record)
        if ultra is not None:
            totals = totals.plus_ultra(ultra)
            continue
        selection = read_selection(record)
        if selection is not None:
            totals = totals.plus_selection(
                model=selection.model,
                model_display=selection.model_display,
                effort=selection.effort,
                ultra=selection.ultra,
            )
            continue
        usage = _usage_of(record)
        if usage is None:
            continue
        message = record.get("message") or {}
        message_id = message.get("id")
        if message_id is not None and message_id == totals.last_message_id:
            continue
        model = message.get("model")
        effort = record.get("effort")
        totals = totals.plus_usage(
            usage,
            model=str(model) if isinstance(model, str) else None,
            effort=str(effort) if isinstance(effort, str) else None,
            message_id=str(message_id) if message_id is not None else None,
        )
    return totals, offset


def read_transcript_totals(
    path: Path,
    *,
    cache: Optional[IncrementalCache] = None,
    max_cold_bytes: Optional[int] = None,
) -> Optional[TranscriptTotals]:
    """Sum one transcript, resuming from the cache when the file only grew.

    Description: stats the file, asks the cache whether the bytes it
      remembers are still the same bytes, and reads only the appended
      tail when they are. Returns None when the file could not be stat'd
      or opened, which the caller reports as ``unchecked`` - never as a
      session that cost nothing.
    Inputs: path (Path) - the transcript. cache (IncrementalCache | None)
      - defaults to the process-wide cache; tests pass their own.
      max_cold_bytes (int | None) - refuse a COLD parse of a file larger
      than this, answering None. Default None caps nothing. See the
      comment at the guard for the measurement behind it.
    Output: TranscriptTotals | None.
    Example: read_transcript_totals(Path("/a.jsonl")).output_tokens
    """
    store = cache if cache is not None else TRANSCRIPT_CACHE
    key = os.path.abspath(str(path))
    try:
        stat = os.stat(key)
    except OSError as exc:
        logger.debug("token_usage_transcript_unreadable", error=str(exc))
        return None
    signature = stat_signature(stat)
    remembered = store.unchanged(key, signature)
    if remembered is not None:
        return remembered
    if (max_cold_bytes is not None and stat.st_size > max_cold_bytes
            and not store.knows(key)):
        return None
    try:
        with open(key, "rb") as handle:
            head = handle.read(HEAD_BYTES)
            resume = store.resume_point(
                key, size=stat.st_size, mtime_ns=stat.st_mtime_ns, head=head
            )
            if resume is None:
                handle.seek(0)
                totals = TranscriptTotals()
            else:
                offset, totals = resume
                handle.seek(offset)
            totals, offset = scan_lines(handle, totals)
    except OSError as exc:
        logger.debug("token_usage_transcript_unreadable", error=str(exc))
        return None
    store.remember(
        key,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        head=head,
        offset=offset,
        totals=totals,
        signature=signature,
    )
    if totals.malformed_lines:
        logger.debug(
            "token_usage_transcript_malformed_lines",
            lines=totals.malformed_lines,
        )
    return totals


def context_used_tokens(totals: TranscriptTotals) -> Optional[int]:
    usage = totals.last_usage
    if not isinstance(usage, dict):
        return None
    return (
        coerce_token_count(usage.get("input_tokens"))
        + coerce_token_count(usage.get("cache_creation_input_tokens"))
        + coerce_token_count(usage.get("cache_read_input_tokens"))
    )
