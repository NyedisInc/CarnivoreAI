
from __future__ import annotations

import os
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import structlog

from src.core.attention.codex_gather import DEFAULT_CODEX_HOME, rollout_path_for
from src.core.session_token_usage import claude_reader, codex_reader
from src.core.session_token_usage.model_table import (
    cost_tier_for_model,
    display_name_for_model,
    estimate_cost_usd,
    window_for_model,
)
from src.core.session_transcript_presence import (
    CONVERSATION_ABSENT,
    CONVERSATION_PRESENT,
)
from src.models.session_token_usage import SessionTokenUsage

logger = structlog.get_logger()

FAMILY_CLAUDE = "claude"
FAMILY_CODEX = "codex"

_LOCATION_CACHE_MAX = 256
_CLAUDE_LOCATION_CACHE: "OrderedDict[tuple, Path]" = OrderedDict()
_CODEX_LOCATION_CACHE: "OrderedDict[tuple, str]" = OrderedDict()


def _cached_location(cache: "OrderedDict[tuple, Any]", key: tuple) -> Optional[Any]:
    value = cache.get(key)
    if value is not None:
        cache.move_to_end(key)
    return value


def _remember_location(cache: "OrderedDict[tuple, Any]", key: tuple, value: Any) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > _LOCATION_CACHE_MAX:
        cache.popitem(last=False)


def reset_location_caches_for_tests() -> None:
    _CLAUDE_LOCATION_CACHE.clear()
    _CODEX_LOCATION_CACHE.clear()


@dataclass(frozen=True)
class SessionSubject:

    agent_family: Optional[str]
    conversation_uuid: Optional[str]
    working_dir: Optional[str]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _remaining_pct(used: Optional[int], window: Optional[int]) -> Optional[float]:
    if used is None or not window or window <= 0:
        return None
    return round(max(0.0, min(100.0, (1.0 - used / window) * 100.0)), 1)


def _unchecked(detail: str, family: Optional[str] = None) -> SessionTokenUsage:
    return SessionTokenUsage(
        state="unchecked", family=family, as_of=_now_iso(), detail=detail
    )


def _absent(detail: str, family: Optional[str]) -> SessionTokenUsage:
    return SessionTokenUsage(
        state="absent", family=family, as_of=_now_iso(), detail=detail
    )


def _ok(
    *,
    family: str,
    model: Optional[str],
    model_display: Optional[str] = None,
    effort: Optional[str] = None,
    input_tokens: int,
    output_tokens: int,
    cache_read: int,
    cache_creation: int,
    used: Optional[int],
    window: Optional[int],
) -> SessionTokenUsage:
    priced = None if model_display else model
    return SessionTokenUsage(
        state="ok",
        family=family,
        model=model,
        model_display_name=model_display or display_name_for_model(model),
        model_cost_tier=cost_tier_for_model(priced),
        effort=effort,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_creation,
        total_tokens=input_tokens + output_tokens + cache_read + cache_creation,
        cost_estimate_usd=estimate_cost_usd(
            priced,
            input_tokens=input_tokens,
            cache_creation_input_tokens=cache_creation,
            cache_read_input_tokens=cache_read,
            output_tokens=output_tokens,
        ),
        context_used_tokens=used,
        context_window_tokens=window,
        context_remaining_pct=_remaining_pct(used, window),
        as_of=_now_iso(),
    )


def _read_claude(
    subject: SessionSubject,
    *,
    projects_dir: Optional[Path],
    max_cold_bytes: Optional[int] = None,
) -> SessionTokenUsage:
    if not subject.conversation_uuid:
        return _absent(
            "this session has no claude conversation id yet, so nothing has "
            "been spent on it",
            FAMILY_CLAUDE,
        )
    cache_key = (
        str(projects_dir) if projects_dir is not None else "",
        subject.conversation_uuid,
    )
    cached_path = _cached_location(_CLAUDE_LOCATION_CACHE, cache_key)
    transcript_path: Optional[Path] = None
    if cached_path is not None:
        try:
            if cached_path.is_file():
                transcript_path = cached_path
        except OSError:
            transcript_path = None
    if transcript_path is None:
        location = claude_reader.locate_transcript(
            subject.conversation_uuid,
            working_dir=subject.working_dir,
            projects_dir=projects_dir,
        )
        if location.outcome == CONVERSATION_ABSENT:
            return _absent(
                location.detail or "no transcript exists for this conversation",
                FAMILY_CLAUDE,
            )
        if location.outcome != CONVERSATION_PRESENT or location.path is None:
            return _unchecked(
                location.detail
                or "the transcript corpus could not be read, so this session's "
                "token usage could not be determined",
                FAMILY_CLAUDE,
            )
        transcript_path = location.path
        _remember_location(_CLAUDE_LOCATION_CACHE, cache_key, transcript_path)
    totals = claude_reader.read_transcript_totals(
        transcript_path, max_cold_bytes=max_cold_bytes
    )
    if totals is None:
        return _unchecked(
            "this session's transcript could not be opened, so its token "
            "usage could not be determined",
            FAMILY_CLAUDE,
        )
    if totals.last_usage is None:
        return _absent(
            "this session has not completed a turn yet, so nothing has "
            "been spent on it",
            FAMILY_CLAUDE,
        )
    used = claude_reader.context_used_tokens(totals)
    return _ok(
        family=FAMILY_CLAUDE,
        model=totals.last_model,
        model_display=totals.last_model_display,
        effort=totals.effective_effort,
        input_tokens=totals.input_tokens,
        output_tokens=totals.output_tokens,
        cache_read=totals.cache_read_input_tokens,
        cache_creation=totals.cache_creation_input_tokens,
        used=used,
        window=window_for_model(None if totals.last_model_display else totals.last_model),
    )


def _read_codex(
    subject: SessionSubject, *, codex_home: Optional[str]
) -> SessionTokenUsage:
    if not subject.conversation_uuid:
        return _absent(
            "this session has no codex thread id yet, so nothing has been "
            "spent on it",
            FAMILY_CODEX,
        )
    home = codex_home or DEFAULT_CODEX_HOME
    cache_key = (home, subject.conversation_uuid)
    path = _cached_location(_CODEX_LOCATION_CACHE, cache_key)
    if path is not None and not os.path.isfile(path):
        path = None
    if path is None:
        try:
            path = rollout_path_for(home, subject.conversation_uuid)
        except OSError as exc:
            logger.debug("token_usage_rollout_lookup_failed", error=str(exc))
            return _unchecked(
                "codex's session store could not be read, so this session's "
                "token usage could not be determined",
                FAMILY_CODEX,
            )
        if not path:
            return _absent(
                "no codex rollout exists for this thread, so nothing has been "
                "spent on it",
                FAMILY_CODEX,
            )
        _remember_location(_CODEX_LOCATION_CACHE, cache_key, path)
    usage = codex_reader.read_codex_usage(path)
    if usage is None:
        return _unchecked(
            "this session's codex rollout could not be opened, so its token "
            "usage could not be determined",
            FAMILY_CODEX,
        )
    if not usage.started:
        return _absent(
            "this codex thread has not started a turn yet, so nothing has "
            "been spent on it",
            FAMILY_CODEX,
        )
    if not usage.has_usage:
        return _absent(
            "this codex thread has not completed a turn yet, so nothing "
            "has been spent on it",
            FAMILY_CODEX,
        )
    return _ok(
        family=FAMILY_CODEX,
        model=usage.model,
        effort=usage.effort,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read=usage.cache_read_input_tokens,
        cache_creation=usage.cache_creation_input_tokens,
        used=usage.context_used_tokens,
        window=usage.context_window_tokens or window_for_model(usage.model),
    )


def read_session_token_usage(
    session_row: SessionSubject,
    *,
    projects_dir: Optional[Path] = None,
    codex_home: Optional[str] = None,
    max_cold_bytes: Optional[int] = None,
) -> SessionTokenUsage:
    family = (session_row.agent_family or "").strip().lower()
    if family == FAMILY_CLAUDE:
        return _read_claude(
            session_row, projects_dir=projects_dir, max_cold_bytes=max_cold_bytes
        )
    if family == FAMILY_CODEX:
        return _read_codex(session_row, codex_home=codex_home)
    if not family:
        return _unchecked(
            "this session's agent family has not been determined, so which "
            "transcript to read is unknown"
        )
    return _unchecked(
        f"there is no token usage reader for the {family} agent, so this "
        "session's usage could not be determined"
    )
