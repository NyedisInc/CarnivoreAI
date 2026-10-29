
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Mapping, Optional

from src.core.byoai import transport
from src.core.byoai.contracts import (
    CAP_DECIDE, EXTRA_LIST_MODELS, EXTRA_TEST, PROTO_JEV, ByoaiError, Connection,
    DecideRequest, DecideResult, ModelInfo, Target, TestResult, Usage,
)
from src.core.byoai.presets import JEV_MODEL

PROTOCOL = PROTO_JEV
CAPABILITIES: frozenset = frozenset({CAP_DECIDE})
EXTRAS: frozenset = frozenset({EXTRA_LIST_MODELS, EXTRA_TEST})

PATH = "/v1/systemone"


def _question(name: str, spec: Mapping[str, Any]) -> Dict[str, Any]:
    kind = spec.get("type")
    text = str(spec.get("instructions") or spec.get("question") or name)
    if kind in ("noul", "bool"):
        return {"type": "noul", "instructions": text}
    if kind == "choice":
        criteria = spec.get("criteria")
        if not isinstance(criteria, Mapping):
            options = spec.get("options") or []
            if not options:
                raise ByoaiError(f"question {name!r} needs options or criteria")
            criteria = {str(o): str(o) for o in options}
        return {"type": "choice", "instructions": text, "criteria": dict(criteria)}
    if kind == "score":
        criteria = spec.get("criteria")
        if not isinstance(criteria, list) or len(criteria) < 2:
            criteria = [f"lowest ({spec.get('min', 0)})", f"highest ({spec.get('max', 1)})"]
        return {"type": "score", "instructions": text, "criteria": list(criteria)}
    raise ByoaiError(f"question {name!r} needs a type of choice, score, noul or bool")


def build_body(request: DecideRequest) -> Dict[str, Any]:
    if not request.questions:
        raise ByoaiError("decide needs at least one question")
    state = request.state if isinstance(request.state, str) else json.dumps(request.state, default=str)
    return {"state": state, "model": JEV_MODEL,
            "questions": {n: _question(n, s) for n, s in request.questions.items()}}


def _answer(spec: Mapping[str, Any], raw: Mapping[str, Any]) -> Dict[str, Any]:
    kind = raw.get("type")
    out: Dict[str, Any] = {}
    if kind == "choice":
        out["value"] = raw.get("choice")
        out["probabilities"] = raw.get("probabilities")
    elif kind == "score":
        score = raw.get("score")
        top = len(raw.get("legend") or {}) - 1
        if spec.get("min") is not None and spec.get("max") is not None and top > 0 and isinstance(score, (int, float)):
            low, high = float(spec["min"]), float(spec["max"])
            score = min(max(low + score / top * (high - low), low), high)
        out["value"] = score
    else:
        probability = raw.get("noul")
        out["probability"] = probability
        out["value"] = (probability >= 0.5) if spec.get("type") == "bool" and isinstance(probability, (int, float)) else probability
    if raw.get("confidence") is not None:
        out["confidence"] = raw["confidence"]
    return {k: v for k, v in out.items() if v is not None}


def parse(request: DecideRequest, body: Mapping[str, Any]) -> DecideResult:
    answers = body.get("answers")
    if not isinstance(answers, Mapping):
        raise ByoaiError("jev answered no answers")
    result: Dict[str, Any] = {}
    for name, spec in request.questions.items():
        if not isinstance(answers.get(name), Mapping):
            raise ByoaiError(f"jev gave no answer for {name!r}")
        result[name] = _answer(spec, answers[name])
    usage = body.get("usage") if isinstance(body.get("usage"), Mapping) else {}
    return DecideResult(answers=result, usage=Usage(input_tokens=usage.get("input_tokens"),
                                                    output_tokens=usage.get("output_tokens")), raw=body)


async def decide(target: Target, key: Optional[str], request: DecideRequest) -> DecideResult:
    response = await transport.request(target.connection, key, "POST", PATH, json=build_body(request),
                                       timeout=30.0)
    try:
        body = response.json()
    except ValueError:
        raise ByoaiError("jev answered something that is not JSON") from None
    return parse(request, body if isinstance(body, dict) else {})


async def list_models(connection: Connection, key: Optional[str]) -> List[ModelInfo]:
    return [ModelInfo(id=JEV_MODEL, capabilities=(CAP_DECIDE,), label=JEV_MODEL)]


async def test(target: Target, key: Optional[str], capability: str) -> TestResult:
    started = time.monotonic()
    request = DecideRequest(state="The sky is blue.", questions={"blue": {"type": "bool", "question": "Is the sky blue?"}})
    try:
        result = await decide(target, key, request)
    except ByoaiError as exc:
        return TestResult(ok=False, capability=CAP_DECIDE, model=JEV_MODEL, detail=f"{type(exc).__name__}: {exc}")
    value = result.answers["blue"].get("value")
    return TestResult(ok=value is True, capability=CAP_DECIDE, latency_ms=int((time.monotonic() - started) * 1000),
                      model=JEV_MODEL, detail=f"blue={value}")
