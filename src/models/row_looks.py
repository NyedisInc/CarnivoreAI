
from __future__ import annotations

from typing import Dict, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.row_looks.palette import COLORS, ICONS, RowLookRefused, checked


def look_checked(color: Optional[str], icon: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    try:
        return checked(color, icon)
    except RowLookRefused as exc:
        raise ValueError(str(exc)) from exc


class RowLookRequest(BaseModel):
    """``PUT /sidebar/row-looks/{row_id}``: change a row's look. An absent field keeps that part, ``null`` clears it."""

    model_config = ConfigDict(extra="forbid")
    color: Optional[str] = Field(None, description=f"A named theme color: {', '.join(COLORS)}.")
    icon: Optional[str] = Field(None, description=f"A named icon: {', '.join(ICONS)}.")

    @model_validator(mode="after")
    def _known_look(self) -> "RowLookRequest":
        if not self.model_fields_set & {"color", "icon"}:
            raise ValueError("send color, icon or both (null clears one)")
        look_checked(self.color, self.icon)
        return self


class RowLookInfo(BaseModel):
    """One row's look; a None part is not set (the row draws it as it always did)."""

    color: Optional[str] = None
    icon: Optional[str] = None


class RowLookList(BaseModel):
    """``GET /sidebar/row-looks``: the look of every styled row, by row id (16-hex)."""

    looks: Dict[str, RowLookInfo]


class RowLookResponse(BaseModel):
    """``PUT /sidebar/row-looks/{row_id}``: the row's look now."""

    row_id: str
    color: Optional[str] = None
    icon: Optional[str] = None
