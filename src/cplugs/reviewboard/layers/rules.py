
from __future__ import annotations

import math
from typing import Any, Collection, Iterable, List, Optional, Sequence, Union

from src.cplugs.reviewboard.layers.models import (ChoiceItem, DateItem, Layer, MultiItem, NumberItem, QuestionsLayer, RankItem, Row, RowChoice,
                                                  RowsLayer)


def _dupes(ids: Iterable[str]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for i in ids:
        if i in seen and i not in out:
            out.append(i)
        seen.add(i)
    return out


def numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def within(value: Any, low: Any, high: Any) -> bool:
    return (low is None or value >= low) and (high is None or value <= high)


def _item_problems(item: Any, where: str) -> List[str]:
    out: List[str] = []
    at = f"{where}.{item.id}"
    if isinstance(item, (ChoiceItem, MultiItem, RankItem)):
        ids = [o.id for o in item.options]
        if _dupes(ids):
            out.append(f"{at}: an option id is used twice")
    if isinstance(item, ChoiceItem) and item.default is not None and item.default not in {o.id for o in item.options}:
        out.append(f"{at}.default: {item.default} is not one of its options")
    elif isinstance(item, MultiItem):
        out += _multi_problems(item, at)
    elif isinstance(item, RankItem) and item.default is not None and sorted(item.default) != sorted(o.id for o in item.options):
        out.append(f"{at}.default: a rank default lists every option once")
    elif isinstance(item, NumberItem):
        out += _number_problems(item, at)
    elif isinstance(item, DateItem):
        if item.min is not None and item.max is not None and item.min > item.max:
            out.append(f"{at}: min is after max")
        if item.default is not None and not within(item.default, item.min, item.max):
            out.append(f"{at}.default: {item.default} is outside min and max")
    return out


def _multi_problems(item: MultiItem, at: str) -> List[str]:
    out: List[str] = []
    if item.min is not None and item.max is not None and item.min > item.max:
        out.append(f"{at}: min is above max")
    if item.min is not None and item.min > len(item.options):
        out.append(f"{at}: min is above the number of options")
    if item.default is not None:
        picks = item.default
        if len(set(picks)) != len(picks) or not set(picks) <= {o.id for o in item.options}:
            out.append(f"{at}.default: picks distinct options of its own")
        elif not within(len(picks), item.min, item.max):
            out.append(f"{at}.default: the number picked is outside min and max")
    return out


def _number_problems(item: NumberItem, at: str) -> List[str]:
    out: List[str] = []
    if item.min is not None and item.max is not None and item.min > item.max:
        out.append(f"{at}: min is above max")
    if item.slider and (item.min is None or item.max is None):
        out.append(f"{at}: a slider needs both min and max")
    if item.default is not None and not (numeric(item.default) and within(item.default, item.min, item.max)):
        out.append(f"{at}.default: {item.default} is outside min and max")
    return out


def _anchor_problems(owner: str, anchor: Optional[str], declared: Collection[str], at: str) -> List[str]:
    if anchor is not None and anchor not in declared:
        return [f"{at}.{owner}: anchor {anchor} is not declared in this revision"]
    return []


def effective_choices(layer: RowsLayer, row: Row) -> Sequence[RowChoice]:
    return row.choices if row.choices is not None else (layer.choices or [])


def _row_problems(layer: RowsLayer, row: Row, at: str) -> List[str]:
    out: List[str] = []
    where = f"{at}.{row.id}"
    own = effective_choices(layer, row)
    ids = [c.id for c in own]
    if not ids:
        return [f"{where}: no choices (give the row choices or the layer choices)"]
    if _dupes(ids):
        out.append(f"{where}.choices: a choice id is used twice")
    if row.suggest is not None and row.suggest not in ids:
        out.append(f"{where}.suggest: {row.suggest} is not one of its choices")
    if row.default is not None:
        picks: Union[str, List[str]] = row.default
        if layer.pick == "one":
            if not isinstance(picks, str) or picks not in ids:
                out.append(f"{where}.default: a pick-one row carries one of its choice ids")
        elif not isinstance(picks, list) or len(set(picks)) != len(picks) or not set(picks) <= set(ids):
            out.append(f"{where}.default: a pick-several row carries a list of distinct choice ids")
    return out


def problems(layer: Layer, anchors: Collection[str], where: str) -> List[str]:
    out: List[str] = []
    if isinstance(layer, QuestionsLayer):
        if _dupes(i.id for i in layer.items):
            out.append(f"{where}.items: an item id is used twice")
        for item in layer.items:
            out += _anchor_problems(item.id, item.anchor, anchors, f"{where}.items")
            out += _item_problems(item, f"{where}.items")
        return out
    if layer.choices is not None and _dupes(c.id for c in layer.choices):
        out.append(f"{where}.choices: a choice id is used twice")
    if _dupes(r.id for r in layer.rows):
        out.append(f"{where}.rows: a row id is used twice")
    for row in layer.rows:
        out += _anchor_problems(row.id, row.anchor, anchors, f"{where}.rows")
        out += _row_problems(layer, row, f"{where}.rows")
    return out
