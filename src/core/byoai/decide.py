
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from src.core.byoai.contracts import ByoaiError, ChatMessage, ChatRequest, DecideRequest, DecideResult, Usage

DEFAULT_SYSTEM = ("You are a decision function. Read the state, answer every question, and reply with "
                  "one JSON object only: no prose, no code fences.")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def choice(options: Sequence[str], question: str = "",
           criteria: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    spec: Dict[str, Any] = {"type": "choice", "options": list(options), "question": question}
    if criteria:
        spec["criteria"] = dict(criteria)
    return spec


def score(low: float = 0.0, high: float = 1.0, question: str = "",
          criteria: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    spec: Dict[str, Any] = {"type": "score", "min": low, "max": high, "question": question}
    if criteria:
        spec["criteria"] = list(criteria)
    return spec


def yes_no(question: str = "") -> Dict[str, Any]:
    return {"type": "bool", "question": question}


def _options(spec: Mapping[str, Any]) -> List[str]:
    criteria = spec.get("criteria")
    return [str(o) for o in spec.get("options") or (criteria if isinstance(criteria, Mapping) else ())]


def _property(name: str, spec: Mapping[str, Any]) -> Dict[str, Any]:
    kind = spec.get("type")
    if kind == "choice" and _options(spec):
        return {"type": "string", "enum": _options(spec)}
    if kind == "score":
        return {"type": "number"}
    if kind == "bool":
        return {"type": "boolean"}
    raise ByoaiError(f"question {name!r} needs a type of choice, score or bool")


def schema_for(questions: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    if not questions:
        raise ByoaiError("decide needs at least one question")
    return {"type": "object", "properties": {n: _property(n, s) for n, s in questions.items()},
            "required": list(questions), "additionalProperties": False}


def _describe(name: str, spec: Mapping[str, Any]) -> str:
    kind = spec.get("type")
    criteria = spec.get("criteria")
    if kind == "choice":
        meant = (", ".join(f"{k} = {v}" for k, v in criteria.items())
                 if isinstance(criteria, Mapping) else ", ".join(_options(spec)))
        how = f"one of: {meant}"
    elif kind == "score":
        scale = f", where {criteria[0]} is the lowest and {criteria[-1]} the highest" \
            if isinstance(criteria, list) and len(criteria) >= 2 else ""
        how = f"a number from {spec.get('min', 0)} to {spec.get('max', 1)}{scale}"
    else:
        how = "true or false"
    asked = spec.get("question") or spec.get("instructions")
    text = f" {asked}" if asked else ""
    return f"- {name}:{text} (answer {how})"


def chat_request(request: DecideRequest) -> ChatRequest:
    state = request.state if isinstance(request.state, str) else json.dumps(request.state, default=str, indent=1)
    lines = "\n".join(_describe(n, s) for n, s in request.questions.items())
    return ChatRequest(messages=(ChatMessage("user", f"State:\n{state}\n\nQuestions:\n{lines}"),),
                       system=request.system or DEFAULT_SYSTEM, temperature=0,
                       json_schema=schema_for(request.questions))


def _object(text: str) -> Dict[str, Any]:
    cleaned = _FENCE.sub("", text.strip())
    for candidate in (cleaned, cleaned[cleaned.find("{"):cleaned.rfind("}") + 1]):
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise ByoaiError("the model's answer was not a JSON object")


def _value(name: str, spec: Mapping[str, Any], raw: Any) -> Any:
    kind = spec.get("type")
    if kind == "choice" and raw in _options(spec):
        return raw
    if kind == "bool" and isinstance(raw, bool):
        return raw
    if kind == "score" and isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return min(max(float(raw), float(spec.get("min", 0))), float(spec.get("max", 1)))
    raise ByoaiError(f"the model's answer to {name!r} does not fit the question")


def parse(text: str, questions: Mapping[str, Mapping[str, Any]], usage: Optional[Usage] = None,
          raw: Any = None) -> DecideResult:
    data = _object(text)
    answers: Dict[str, Any] = {}
    for name, spec in questions.items():
        if name not in data:
            raise ByoaiError(f"the model gave no answer for {name!r}")
        answers[name] = {"value": _value(name, spec, data[name])}
    return DecideResult(answers=answers, usage=usage or Usage(), raw=raw)
