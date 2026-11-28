
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.agy.state import state_for_conversation
from src.models.session_token_usage import SessionTokenUsage

FAMILY_AGY = "agy"


def _int(value: Any) -> Optional[int]:
    return int(value) if isinstance(value, (int, float)) and value >= 0 else None


_EFFORT_SUFFIX_RE = re.compile(r"\s*\(([^()]+)\)\s*$")


def split_model_name(display: Any, effort: Any) -> tuple:
    name = display.strip() if isinstance(display, str) and display.strip() else None
    eff = effort.strip() if isinstance(effort, str) and effort.strip() else None
    match = _EFFORT_SUFFIX_RE.search(name or "")
    if match and name[:match.start()].strip():
        eff = eff or match.group(1).strip().lower()
        name = name[:match.start()].strip()
    return name, eff


def usage_from_state(state: Dict[str, Any]) -> SessionTokenUsage:
    window = state.get("context_window") if isinstance(state.get("context_window"), dict) else {}
    current = window.get("current_usage") if isinstance(window.get("current_usage"), dict) else {}
    model = state.get("model") if isinstance(state.get("model"), dict) else {}
    cost = state.get("cost") if isinstance(state.get("cost"), dict) else {}
    size = _int(window.get("context_window_size")) or None
    remaining = window.get("remaining_percentage")
    used = None
    pct = window.get("used_percentage")
    if isinstance(pct, (int, float)) and not isinstance(pct, bool) and size:
        used = round(pct / 100 * size)
    elif current:
        used = sum(_int(current.get(k)) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    inp, out = _int(window.get("total_input_tokens")), _int(window.get("total_output_tokens"))
    name, effort = split_model_name(model.get("display_name"), model.get("effort"))
    return SessionTokenUsage(
        state="ok", family=FAMILY_AGY, model=model.get("id"), model_display_name=name,
        effort=effort, input_tokens=inp, output_tokens=out,
        total_tokens=(inp or 0) + (out or 0) if inp is not None or out is not None else None,
        cost_estimate_usd=cost.get("total_usd") if isinstance(cost.get("total_usd"), (int, float)) else None,
        context_used_tokens=used, context_window_tokens=size,
        context_remaining_pct=float(remaining) if isinstance(remaining, (int, float)) else None,
        as_of=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    )


def read_agy_usage(state_dir: Path, conversation_uuid: Optional[str]) -> Optional[SessionTokenUsage]:
    state = state_for_conversation(state_dir, conversation_uuid)
    return usage_from_state(state) if state is not None else None
