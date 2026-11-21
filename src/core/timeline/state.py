
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Mapping, Optional

from src.core.attention.transcript_facts import TranscriptFacts
from src.core.timeline.fold import ConvState

COVERAGE_WHOLE, COVERAGE_WINDOW = "whole", "window"


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def transcript_fields(state: ConvState, facts: TranscriptFacts) -> Dict[str, Any]:
    return {
        "coverage": COVERAGE_WHOLE if state.whole else COVERAGE_WINDOW,
        "leaf_uuid": state.leaf_uuid,
        "open_turn": state.open_turn,
        "verdict": facts.verdict,
        "turn_end_kind": facts.turn_end_kind,
        "turn_end_at": _iso(facts.turn_end_at),
        "pending_agents": facts.pending_background_agents,
        "pending_workflows": facts.pending_workflows,
        "newest_assistant_at": _iso(facts.newest_assistant_at),
        "newest_append_at": _iso(facts.newest_append_at),
        "newest_prompt_at": _iso(facts.newest_user_prompt_at),
        "blocked_on_tool": facts.blocked_on_tool,
        "queued_reinvoke": facts.queued_reinvoke,
        "open_agents": facts.open_async_agents,
        "open_background": facts.open_background_tasks,
        "open_workflows": facts.open_workflows,
    }


def changed_fields(before: Mapping[str, Any], after: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in after.items() if key not in before or before[key] != value}
