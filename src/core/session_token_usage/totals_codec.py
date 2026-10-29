
from __future__ import annotations

import dataclasses
from typing import Any, Dict

from src.core.session_token_usage.persist_spec import PersistSpec

_INT_FIELDS = (
    "input_tokens", "output_tokens", "cache_read_input_tokens",
    "cache_creation_input_tokens", "malformed_lines",
)
_STR_FIELDS = ("last_model", "last_effort", "last_model_display", "last_message_id")


def encode_totals(totals: Any) -> Dict[str, Any]:
    return dataclasses.asdict(totals)


def decode_totals(value: Any) -> Any:
    from src.core.session_token_usage.cache import TranscriptTotals

    if not isinstance(value, dict):
        raise TypeError("totals payload must be an object")
    names = {f.name for f in dataclasses.fields(TranscriptTotals)}
    if set(value) != names:
        raise ValueError("totals payload fields do not match the type")
    for name in _INT_FIELDS:
        if not isinstance(value[name], int) or isinstance(value[name], bool):
            raise TypeError(f"{name} must be an int")
    for name in _STR_FIELDS:
        if value[name] is not None and not isinstance(value[name], str):
            raise TypeError(f"{name} must be a string or null")
    if value["last_usage"] is not None and not isinstance(value["last_usage"], dict):
        raise TypeError("last_usage must be an object or null")
    if not isinstance(value["ultra_effort"], bool):
        raise TypeError("ultra_effort must be a bool")
    return TranscriptTotals(**value)


TRANSCRIPT_TOTALS_SPEC = PersistSpec(
    name="token_usage.transcript_totals",
    manual_version=1,
    sources=(
        "src.core.session_token_usage.claude_reader",
        "src.core.session_token_usage.claude_selection",
        "src.core.session_token_usage.model_table",
        "src.core.session_token_usage.cache",
        "src.core.session_token_usage.persist_spec",
        "src.core.session_token_usage.totals_codec",
    ),
    encode=encode_totals,
    decode=decode_totals,
)
