
from __future__ import annotations

from typing import Any, List, Mapping

from pydantic import TypeAdapter, ValidationError

from src.plugins.reviewboard import rules
from src.plugins.reviewboard.errors import BadRequest
from src.plugins.reviewboard.layers.models import QuestionsLayer
from src.plugins.reviewboard.payloads import check_fits_layer
from src.plugins.reviewboard.schema import Answer, Payload, Revision, Round

_PAYLOAD = TypeAdapter(Payload)


def _answers(rev: Revision, given: Any) -> List[str]:
    if rev.payload_mode:
        return [f"{rev.id} takes its answers as a payload"]
    try:
        parsed = [Answer.model_validate(item) for item in given]
    except ValidationError:
        return ["an answer does not have the board's answer shape"]
    probe = Round.model_construct(answers=parsed, anchor_notes=[], unanswered=[], note="")
    return rules.answer_problems(probe, "answers", rev)


def _payload(rev: Revision, given: Any) -> List[str]:
    if not rev.payload_mode:
        return [f"{rev.id} does not take a payload"]
    try:
        payload = _PAYLOAD.validate_python(given)
        check_fits_layer(rev.model_dump(mode="json"), rev.id, payload)
    except ValidationError:
        return ["the payload is not a JSON object the board can hold"]
    except BadRequest as exc:
        return [str(exc)]
    return []


def _layer_items(rev: Revision) -> List[str]:
    if rev.layer is None:
        return []
    return [i.id for i in rev.layer.items] if isinstance(rev.layer, QuestionsLayer) else [r.id for r in rev.layer.rows]


def _comment(rev: Revision, body: Mapping[str, Any]) -> List[str]:
    if "anchor" in body and body["anchor"] not in {a.id for a in rev.anchors}:
        return [f"anchor {body['anchor']} is not declared in {rev.id}"]
    if "item" in body and body["item"] not in _layer_items(rev):
        return [f"item {body['item']} is not an item of {rev.id}'s layer"]
    return []


def problems(rev: Revision, kind: str, body: Mapping[str, Any]) -> List[str]:
    if kind == "comment":
        return _comment(rev, body)
    if kind != "answers":
        return [f"{kind} is not a kind of post"]
    return _payload(rev, body["payload"]) if "payload" in body else _answers(rev, body.get("answers"))
