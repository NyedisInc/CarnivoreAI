
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional

import structlog

from src.core.session_token_usage.cache import coerce_token_count

logger = structlog.get_logger()

TAIL_BYTES = 4 * 1024 * 1024

HEAD_BYTES = 1024 * 1024


@dataclass(frozen=True)
class CodexUsage:

    started: bool
    has_usage: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    context_used_tokens: Optional[int] = None
    context_window_tokens: Optional[int] = None
    model: Optional[str] = None
    effort: Optional[str] = None


def _records_in(blob: bytes, *, drop_first_partial: bool) -> Iterator[Dict[str, Any]]:
    lines = blob.split(b"\n")
    if drop_first_partial and lines:
        lines = lines[1:]
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(record, dict):
            yield record


def _payload_of(record: Dict[str, Any], record_type: str) -> Optional[Dict[str, Any]]:
    if record.get("type") != record_type:
        return None
    payload = record.get("payload")
    return payload if isinstance(payload, dict) else None


def read_codex_usage(path: str) -> Optional[CodexUsage]:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            window = min(size, TAIL_BYTES)
            handle.seek(size - window)
            tail = handle.read(window)
            head = tail if window >= size else None
            if head is None:
                handle.seek(0)
                head = handle.read(min(size, HEAD_BYTES))
    except OSError as exc:
        logger.debug("token_usage_rollout_unreadable", error=str(exc))
        return None

    info: Optional[Dict[str, Any]] = None
    model: Optional[str] = None
    effort: Optional[str] = None
    seen_meta = False
    for record in _records_in(tail, drop_first_partial=window < size):
        payload = _payload_of(record, "event_msg")
        if payload is not None and payload.get("type") == "token_count":
            candidate = payload.get("info")
            if isinstance(candidate, dict):
                info = candidate
        turn = _payload_of(record, "turn_context")
        if turn is not None and isinstance(turn.get("model"), str):
            model = turn["model"]
        if turn is not None and isinstance(turn.get("effort"), str):
            effort = turn["effort"]
        if record.get("type") == "session_meta":
            seen_meta = True

    if model is None or effort is None or not seen_meta:
        for record in _records_in(head, drop_first_partial=False):
            if record.get("type") == "session_meta":
                seen_meta = True
                meta = record.get("payload")
                if model is None and isinstance(meta, dict):
                    if isinstance(meta.get("model"), str):
                        model = meta["model"]
            turn = _payload_of(record, "turn_context")
            if model is None and turn is not None and isinstance(turn.get("model"), str):
                model = turn["model"]
            if effort is None and turn is not None and isinstance(turn.get("effort"), str):
                effort = turn["effort"]

    if info is None:
        return CodexUsage(started=seen_meta, has_usage=False, model=model, effort=effort)

    return _usage_from_info(info, model=model, effort=effort, started=True)


def _usage_from_info(
    info: Dict[str, Any],
    *,
    model: Optional[str],
    effort: Optional[str] = None,
    started: bool,
) -> CodexUsage:
    totals = info.get("total_token_usage")
    totals = totals if isinstance(totals, dict) else {}
    last = info.get("last_token_usage")
    last = last if isinstance(last, dict) else {}

    inclusive_input = coerce_token_count(totals.get("input_tokens"))
    cache_read = coerce_token_count(totals.get("cached_input_tokens"))
    cache_write = coerce_token_count(totals.get("cache_write_input_tokens"))
    fresh_input = max(0, inclusive_input - cache_read - cache_write)

    window = info.get("model_context_window")
    used = coerce_token_count(last.get("input_tokens")) if last else None

    return CodexUsage(
        started=started,
        has_usage=True,
        input_tokens=fresh_input,
        output_tokens=coerce_token_count(totals.get("output_tokens")),
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
        context_used_tokens=used,
        context_window_tokens=(
            int(window) if isinstance(window, (int, float)) and window > 0 else None
        ),
        model=model,
        effort=effort,
    )
