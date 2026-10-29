
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import structlog

from src.core.attention.codex_gather import DEFAULT_CODEX_HOME, rollout_path_for
from src.core.attention.codex_reader import CodexEvidence
from src.core.attention.registry_record import REG_OK, RegistryRecord
from src.core.attention.registry_index import read_registry_index, registry_for_session
from src.core.claude_config.profile_roots import claude_registry_roots, registry_file_path
from src.core.auto_sleep.idle_seed import (
    SOURCE_CLAUDE_REGISTRY,
    SOURCE_CLAUDE_TRANSCRIPT,
    SOURCE_CODEX_ROLLOUT,
    SOURCE_CODEX_STATUS,
)

logger = structlog.get_logger()

_STAT_ERRORS = (OSError, ValueError)


def stat_mtime(path: Optional[str]) -> Optional[datetime]:
    if not path:
        return None
    try:
        return datetime.fromtimestamp(os.stat(path).st_mtime, tz=timezone.utc)
    except _STAT_ERRORS:
        return None


def _epoch_seconds_to_datetime(epoch: Optional[int]) -> Optional[datetime]:
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    except (OverflowError, OSError, ValueError, TypeError):
        return None


def resolve_claude_seed(
    *,
    registry: RegistryRecord,
    cwd: Optional[str],
    claude_session_uuid: Optional[str],
    tmux_name: Optional[str],
    session_started_epoch: Optional[int],
    config_path: Path,
) -> Tuple[List[Tuple[Optional[datetime], str]], Optional[datetime]]:
    candidates: List[Tuple[Optional[datetime], str]] = []
    floor: Optional[datetime] = None
    resolved = registry

    if resolved.verdict != REG_OK:
        for directory in claude_registry_roots(config_path):
            index = read_registry_index(str(directory))
            candidate = registry_for_session(
                tmux_name=tmux_name,
                index=index,
                session_started_epoch=session_started_epoch,
                claude_session_uuid=claude_session_uuid,
            )
            if candidate.verdict == REG_OK:
                resolved = candidate
                registry_path = os.path.join(str(directory), "%s.json" % candidate.pid)
                candidates.append((stat_mtime(registry_path), SOURCE_CLAUDE_REGISTRY))
                break
    else:
        registry_path = registry_file_path(resolved.pid)
        candidates.append((stat_mtime(registry_path), SOURCE_CLAUDE_REGISTRY))

    if resolved.verdict == REG_OK:
        floor = resolved.started_at
    if floor is None:
        floor = _epoch_seconds_to_datetime(session_started_epoch)

    if claude_session_uuid:
        try:
            from src.core.session_transcript_presence import conversation_presence

            presence = conversation_presence(claude_session_uuid, working_dir=cwd)
            transcript_path = str(presence.path) if presence.path else None
        except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
            logger.debug("idle_seed_transcript_unreadable", error=type(exc).__name__)
            transcript_path = None
        candidates.append((stat_mtime(transcript_path), SOURCE_CLAUDE_TRANSCRIPT))

    return candidates, floor


def resolve_codex_seed(
    *,
    codex: Optional[CodexEvidence],
    codex_session_uuid: Optional[str],
    session_started_epoch: Optional[int],
    codex_home: str = DEFAULT_CODEX_HOME,
) -> Tuple[List[Tuple[Optional[datetime], str]], Optional[datetime]]:
    candidates: List[Tuple[Optional[datetime], str]] = []
    if codex is not None:
        candidates.append((codex.transcript.last_append_at, SOURCE_CODEX_STATUS))
    rollout_path = (
        rollout_path_for(codex_home, codex_session_uuid) if codex_session_uuid else None
    )
    candidates.append((stat_mtime(rollout_path), SOURCE_CODEX_ROLLOUT))
    floor = _epoch_seconds_to_datetime(session_started_epoch)
    return candidates, floor
