
from __future__ import annotations

from typing import Any, Dict, List, Mapping

from pydantic import TypeAdapter

from src.cplugs.reviewboard.layers import rules
from src.cplugs.reviewboard.layers.models import (LAYER_VERSION, MAX_LONG_TEXT, MAX_SHORT_TEXT, ChoiceItem, DateItem, Layer, LongTextItem, MultiItem, NumberItem,
                                                  QuestionsLayer, RankItem, RowsLayer, TextItem, ToggleItem, YesNoItem, is_real_day)
from src.cplugs.reviewboard.schema import MAX_TEXT

ENVELOPE = frozenset({"layer", "v", "values", "notes"})
LAYER_ADAPTER: TypeAdapter = TypeAdapter(Layer)


def _is_text(value: Any, limit: int) -> bool:
    return isinstance(value, str) and len(value) <= limit


def _distinct_subset(value: Any, ids: List[str]) -> bool:
    return isinstance(value, list) and len(set(map(str, value))) == len(value) and all(isinstance(v, str) and v in ids for v in value)


def _value_problem(item: Any, value: Any) -> str:
    if isinstance(item, (YesNoItem, ToggleItem)):
        return "" if isinstance(value, bool) else "a yes/no or toggle value is true or false"
    if isinstance(item, ChoiceItem):
        return "" if isinstance(value, str) and value in [o.id for o in item.options] else "a choice value is one of its option ids"
    if isinstance(item, MultiItem):
        ok = _distinct_subset(value, [o.id for o in item.options]) and (item.max is None or len(value) <= item.max)
        return "" if ok else "a multi value is a list of distinct option ids, at most max of them"
    if isinstance(item, RankItem):
        ok = isinstance(value, list) and all(isinstance(v, str) for v in value) and sorted(value) == sorted(o.id for o in item.options)
        return "" if ok else "a rank value lists every option id once"
    if isinstance(item, TextItem):
        return "" if _is_text(value, MAX_SHORT_TEXT) else f"a text value is a string of at most {MAX_SHORT_TEXT} characters"
    if isinstance(item, LongTextItem):
        return "" if _is_text(value, MAX_LONG_TEXT) else f"a long text value is a string of at most {MAX_LONG_TEXT} characters"
    if isinstance(item, NumberItem):
        ok = rules.numeric(value) and rules.within(value, item.min, item.max)
        return "" if ok else "a number value is finite and within min and max"
    if isinstance(item, DateItem):
        ok = isinstance(value, str) and is_real_day(value) and rules.within(value, item.min, item.max)
        return "" if ok else "a date value is a YYYY-MM-DD day within min and max"
    return "an unknown item kind"


def _row_problem(layer: RowsLayer, row_id: str, value: Any) -> str:
    row = next(r for r in layer.rows if r.id == row_id)
    ids = [c.id for c in rules.effective_choices(layer, row)]
    if layer.pick == "one":
        return "" if isinstance(value, str) and value in ids else "a pick-one value is one of the row's choice ids"
    return "" if _distinct_subset(value, ids) else "a pick-several value is a list of distinct choice ids of the row"


def problems(layer: Layer, payload: Mapping[str, Any]) -> List[str]:
    out: List[str] = []
    extra = sorted(set(payload) - ENVELOPE)
    if extra:
        out.append(f"the payload carries {', '.join(extra)}; a {layer.kind} payload holds layer, v, values and notes")
    if payload.get("layer") != layer.kind or payload.get("v") != LAYER_VERSION:
        out.append(f"the payload is not a {layer.kind} layer v{LAYER_VERSION} payload (layer and v)")
    values, notes = payload.get("values"), payload.get("notes", {})
    if not isinstance(values, dict):
        out.append("values is an object of item id to value")
        values = {}
    if not isinstance(notes, dict):
        out.append("notes is an object of item id to text")
        notes = {}
    known: Dict[str, Any] = {i.id: i for i in layer.items} if isinstance(layer, QuestionsLayer) else {r.id: r for r in layer.rows}
    for key, value in values.items():
        if key not in known:
            out.append(f"values.{key}: the layer has no item {key}")
            continue
        why = _value_problem(known[key], value) if isinstance(layer, QuestionsLayer) else _row_problem(layer, key, value)
        if why:
            out.append(f"values.{key}: {why}")
    for key, text in notes.items():
        if key not in known:
            out.append(f"notes.{key}: the layer has no item {key}")
        elif not _is_text(text, MAX_TEXT):
            out.append(f"notes.{key}: a note is a string of at most {MAX_TEXT} characters")
    return out
