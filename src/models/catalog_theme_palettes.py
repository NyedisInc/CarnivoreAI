
from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, Field


class ThemePaletteEntry(BaseModel):
    """One theme's reduced palette, tied to the digest it was read under.

    Inputs (constructor): digest (str) - the verified folder digest.
      version (str). cssVars (dict[str, str]) - safe colour values by
      custom property. xterm (dict[str, str]) - safe terminal colours.
      ascii (bool) - the theme turns the ascii display on.
    Output: none, it is a record.
    Example: ThemePaletteEntry(digest="ab" * 32, version="1.0.0", cssVars={}, xterm={}, ascii=False)
    """

    digest: str
    version: str
    cssVars: Dict[str, str] = Field(default_factory=dict)
    xterm: Dict[str, str] = Field(default_factory=dict)
    ascii: bool = False


class ThemePalettesResponse(BaseModel):
    """The palettes derived so far, and the theme ids not derived yet.

    Inputs (constructor): items (dict[str, ThemePaletteEntry]) - by item id.
      pending (list[str]) - ids whose read was busy; ask again later.
    Output: none, it is a record.
    Example: ThemePalettesResponse(items={}, pending=["nyedis/snes"])
    """

    items: Dict[str, ThemePaletteEntry] = Field(default_factory=dict)
    pending: List[str] = Field(default_factory=list)
