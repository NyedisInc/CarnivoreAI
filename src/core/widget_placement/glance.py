
from __future__ import annotations

import re
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator

# the glance area
MAX_GLANCE_PLACEMENTS = 12

MAX_PLACEMENT_OPTIONS = 8

MAX_OPTION_TEXT = 128

PLACEMENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")

OPTION_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

WIDGET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

OptionValue = Union[StrictBool, StrictInt, StrictStr]


def check_option_values(value: Dict[str, OptionValue], limit: int) -> Dict[str, OptionValue]:
    if len(value) > limit:
        raise ValueError(f"at most {limit} options on a placement")
    for key, option in value.items():
        if not OPTION_KEY_RE.match(key):
            raise ValueError("an option key is lowercase letters, digits and underscores")
        if isinstance(option, str) and len(option) > MAX_OPTION_TEXT:
            raise ValueError(f"an option value is at most {MAX_OPTION_TEXT} characters")
    return value


class GlancePlacement(BaseModel):
    """One tile placement in the glance area.

    Attributes:
      id (str): the placement's own id, unique in the area.
      widget (str): the widget id, ``core.ledger``.
      options (dict): placement-scoped options, ``{"account": "acc_1"}``;
        empty means every option on its default.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    widget: str
    options: Dict[str, OptionValue] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not PLACEMENT_ID_RE.match(value):
            raise ValueError("a glance placement id is short, lowercase letters, digits and dashes")
        return value

    @field_validator("widget")
    @classmethod
    def _widget(cls, value: str) -> str:
        if not WIDGET_ID_RE.match(value):
            raise ValueError("a glance widget is an id like 'core.ledger'")
        return value

    @field_validator("options")
    @classmethod
    def _options(cls, value: Dict[str, OptionValue]) -> Dict[str, OptionValue]:
        return check_option_values(value, MAX_PLACEMENT_OPTIONS)


def check_placements(value: Optional[List[GlancePlacement]]) -> Optional[List[GlancePlacement]]:
    if value is None:
        return None
    if len(value) > MAX_GLANCE_PLACEMENTS:
        raise ValueError(f"at most {MAX_GLANCE_PLACEMENTS} glance placements")
    seen = set()
    for placement in value:
        if placement.id in seen:
            raise ValueError("a glance placement id appears once")
        seen.add(placement.id)
    return value
