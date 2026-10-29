
from __future__ import annotations

from datetime import date as _date
from typing import Annotated, ClassVar, FrozenSet, List, Literal, Optional, Union

from pydantic import AfterValidator, Field, StrictBool, StrictFloat, StrictInt, StringConstraints

from src.cplugs.reviewboard.layers.base import ItemId, SidecarModel

LAYER_VERSION = 1
MAX_ITEMS = 60
MAX_ROWS = 200
MAX_CHOICES = 12
MAX_OPTIONS = 12
MAX_RANK_OPTIONS = 30
MAX_LINES = 8
MAX_LAYER_TITLE = 120
MAX_INTRO = 600
MAX_LABEL = 300
MAX_HELP = 600
MAX_ROW_TITLE = 200
MAX_TAG = 40
MAX_META = 80
MAX_LINE_LABEL = 60
MAX_LINE_TEXT = 1000
MAX_SHORT_TEXT = 300
MAX_LONG_TEXT = 4000
MAX_NAME = 120
MAX_UNIT = 20


def _text(limit: int):
    return Annotated[str, StringConstraints(min_length=1, max_length=limit)]


def is_real_day(value: str) -> bool:
    if len(value) != 10:
        return False
    try:
        _date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _real_date(value: str) -> str:
    if not is_real_day(value):
        raise ValueError(f"{value} is not a calendar day")
    return value


Day = Annotated[str, StringConstraints(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"), AfterValidator(_real_date)]
Num = Union[StrictInt, Annotated[StrictFloat, Field(allow_inf_nan=False)]]
Placement = Literal["inline", "float"]


class LayerOption(SidecarModel):

    id: ItemId
    label: _text(MAX_NAME)


class _Item(SidecarModel):

    SPARSE: ClassVar[FrozenSet[str]] = frozenset({"help", "anchor", "group", "required", "default"})
    id: ItemId
    kind: str
    label: _text(MAX_LABEL)
    help: Optional[_text(MAX_HELP)] = None
    anchor: Optional[ItemId] = None
    group: Optional[_text(MAX_NAME)] = None
    required: Optional[StrictBool] = None


class YesNoItem(_Item):

    SPARSE: ClassVar[FrozenSet[str]] = _Item.SPARSE
    kind: Literal["yesno"]


class ToggleItem(_Item):

    kind: Literal["toggle"]
    default: Optional[StrictBool] = None


class ChoiceItem(_Item):

    kind: Literal["choice"]
    options: List[LayerOption] = Field(min_length=1, max_length=MAX_OPTIONS)
    default: Optional[ItemId] = None


class MultiItem(_Item):

    SPARSE: ClassVar[FrozenSet[str]] = _Item.SPARSE | {"min", "max"}
    kind: Literal["multi"]
    options: List[LayerOption] = Field(min_length=1, max_length=MAX_OPTIONS)
    min: Optional[int] = Field(default=None, ge=0, le=MAX_OPTIONS)
    max: Optional[int] = Field(default=None, ge=1, le=MAX_OPTIONS)
    default: Optional[List[ItemId]] = Field(default=None, max_length=MAX_OPTIONS)


class RankItem(_Item):

    kind: Literal["rank"]
    options: List[LayerOption] = Field(min_length=2, max_length=MAX_RANK_OPTIONS)
    default: Optional[List[ItemId]] = Field(default=None, max_length=MAX_RANK_OPTIONS)


class TextItem(_Item):

    SPARSE: ClassVar[FrozenSet[str]] = _Item.SPARSE | {"placeholder"}
    kind: Literal["text"]
    placeholder: Optional[_text(MAX_NAME)] = None
    default: Optional[Annotated[str, StringConstraints(max_length=MAX_SHORT_TEXT)]] = None


class LongTextItem(_Item):

    SPARSE: ClassVar[FrozenSet[str]] = _Item.SPARSE | {"placeholder"}
    kind: Literal["longtext"]
    placeholder: Optional[_text(MAX_NAME)] = None
    default: Optional[Annotated[str, StringConstraints(max_length=MAX_LONG_TEXT)]] = None


class NumberItem(_Item):

    SPARSE: ClassVar[FrozenSet[str]] = _Item.SPARSE | {"min", "max", "step", "unit", "slider"}
    kind: Literal["number"]
    min: Optional[Num] = None
    max: Optional[Num] = None
    step: Optional[Annotated[Num, Field(gt=0)]] = None
    unit: Optional[_text(MAX_UNIT)] = None
    slider: Optional[StrictBool] = None
    default: Optional[Num] = None


class DateItem(_Item):

    SPARSE: ClassVar[FrozenSet[str]] = _Item.SPARSE | {"min", "max"}
    kind: Literal["date"]
    min: Optional[Day] = None
    max: Optional[Day] = None
    default: Optional[Day] = None


Item = Annotated[Union[YesNoItem, ToggleItem, ChoiceItem, MultiItem, RankItem, TextItem, LongTextItem, NumberItem, DateItem], Field(discriminator="kind")]


class _LayerBase(SidecarModel):

    SPARSE: ClassVar[FrozenSet[str]] = frozenset({"intro"})
    kind: str
    v: Literal[1]
    title: _text(MAX_LAYER_TITLE)
    intro: Optional[_text(MAX_INTRO)] = None
    placement: Placement = "inline"


class QuestionsLayer(_LayerBase):

    kind: Literal["questions"]
    items: List[Item] = Field(min_length=1, max_length=MAX_ITEMS)


class RowChoice(SidecarModel):

    SPARSE: ClassVar[FrozenSet[str]] = frozenset({"tone"})
    id: ItemId
    label: _text(MAX_NAME)
    tone: Optional[Literal["ok", "push", "later", "none"]] = None


class RowLine(SidecarModel):

    label: _text(MAX_LINE_LABEL)
    text: _text(MAX_LINE_TEXT)


class Row(SidecarModel):

    SPARSE: ClassVar[FrozenSet[str]] = frozenset({"tag", "lines", "meta", "group", "anchor", "choices", "suggest", "default"})
    id: ItemId
    title: _text(MAX_ROW_TITLE)
    tag: Optional[_text(MAX_TAG)] = None
    lines: Optional[List[RowLine]] = Field(default=None, max_length=MAX_LINES)
    meta: Optional[_text(MAX_META)] = None
    group: Optional[_text(MAX_NAME)] = None
    anchor: Optional[ItemId] = None
    choices: Optional[List[RowChoice]] = Field(default=None, min_length=1, max_length=MAX_CHOICES)
    suggest: Optional[ItemId] = None
    default: Optional[Union[ItemId, List[ItemId]]] = None


class RowsLayer(_LayerBase):

    kind: Literal["rows"]
    pick: Literal["one", "several"] = "one"
    choices: Optional[List[RowChoice]] = Field(default=None, min_length=1, max_length=MAX_CHOICES)
    rows: List[Row] = Field(min_length=1, max_length=MAX_ROWS)

    SPARSE: ClassVar[FrozenSet[str]] = _LayerBase.SPARSE | {"choices"}


class CanvasLayer(SidecarModel):

    kind: Literal["canvas"]


Layer = Annotated[Union[QuestionsLayer, RowsLayer], Field(discriminator="kind")]
RequestLayer = Annotated[Union[CanvasLayer, QuestionsLayer, RowsLayer], Field(discriminator="kind")]
