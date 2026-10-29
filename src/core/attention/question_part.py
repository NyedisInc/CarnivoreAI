
from __future__ import annotations

from dataclasses import replace
from typing import Any, Optional

from src.core.attention.evidence import (
    STATE_NEEDS_USER,
    REASON_QUESTION,
    AttentionVerdict,
    Evidence,
)

HINT_QUESTION: str = "question"

HINT_QUESTION_PART_PREFIX: str = "question:"


def question_hint_for(dialog: Any) -> str:
    tabs = getattr(dialog, "tabs", None) or ()
    index: Optional[int] = getattr(dialog, "question_index", None)
    if len(tabs) >= 2 and isinstance(index, int) and 1 <= index <= len(tabs):
        return f"{HINT_QUESTION_PART_PREFIX}{index}/{len(tabs)}"
    return HINT_QUESTION


def with_question_hint(verdict: AttentionVerdict, evidence: Evidence) -> AttentionVerdict:
    if (
        verdict.state != STATE_NEEDS_USER
        or verdict.reason != REASON_QUESTION
        or verdict.activity_hint is not None
    ):
        return verdict
    return replace(verdict, activity_hint=question_hint_for(evidence.dialog))
