
from __future__ import annotations

import json
from typing import Any, List, Mapping, Sequence, Tuple

from src.cplugs.huddle import rich_ask, rules
from src.cplugs.huddle.rules import TaskManagerInvalid


MAX_QUESTIONS = 20
MAX_QUESTION = 500


def build(text: Any, context: Any, questions: Any) -> Tuple[str, str]:
    if questions is None:
        if context not in (None, ""):
            raise TaskManagerInvalid("context needs questions: list the questions to answer")
        return rules.clean_text(text, "text", rules.MAX_MESSAGE), ""
    if not isinstance(questions, list) or not questions:
        raise TaskManagerInvalid("questions must be a non-empty list of short questions")
    if len(questions) > MAX_QUESTIONS:
        raise TaskManagerInvalid(f"at most {MAX_QUESTIONS} questions per ask")
    if any(not isinstance(q, str) for q in questions):
        return _build_typed(context, questions)
    cleaned = [rules.clean_text(q, "each question", MAX_QUESTION) for q in questions]
    background = rules.clean_text(context, "context", rules.MAX_MESSAGE, allow_blank=True) if context is not None else ""
    flat = flatten(background, cleaned)
    if len(flat) > rules.MAX_MESSAGE:
        raise TaskManagerInvalid(f"context and questions are over the {rules.MAX_MESSAGE} character limit together")
    return flat, json.dumps({"context": background, "questions": cleaned}, ensure_ascii=False)


def _build_typed(context: Any, questions: Sequence[Any]) -> Tuple[str, str]:
    background = rules.clean_text(context, "context", rules.MAX_MESSAGE, allow_blank=True) if context is not None else ""
    normalized, _typed = rich_ask.normalize(questions)
    flat = rich_ask.flatten(background, normalized)
    if len(flat) > rules.MAX_MESSAGE:
        raise TaskManagerInvalid(f"context and questions are over the {rules.MAX_MESSAGE} character limit together")
    return flat, rich_ask.dump(background, normalized)


def question_ids(parts: str) -> List[str]:
    form = rich_ask.form_of(parts)
    if form is not None:
        return [q["id"] for q in form]
    _context, strings = wire({"parts": parts})
    return [f"q{at}" for at in range(1, len(strings) + 1)]


def form_of_row(row: Mapping[str, Any]) -> List[dict]:
    form = rich_ask.form_of(row["parts"] if "parts" in row.keys() else "")
    if form is not None:
        return form
    _context, strings = wire(row)
    return [{"id": f"q{at}", "type": rich_ask.LONG_TEXT, "prompt": q, "required": False} for at, q in enumerate(strings or [row["text"]], 1)]


def flatten(context: str, questions: Sequence[str]) -> str:
    numbered = "\n".join(f"{n}. {q}" for n, q in enumerate(questions, 1))
    return f"{context}\n\n{numbered}" if context else numbered


def wire(row: Mapping[str, Any]) -> Tuple[str, List[str]]:
    raw = row["parts"] if "parts" in row.keys() else ""
    if not raw:
        return "", []
    try:
        data = json.loads(raw)
        return str(data.get("context", "")), [str(q["prompt"] if isinstance(q, dict) else q) for q in data.get("questions", [])]
    except (ValueError, AttributeError, TypeError):
        return "", []


__all__ = ["MAX_QUESTION", "MAX_QUESTIONS", "build", "flatten", "form_of_row", "question_ids", "wire"]
