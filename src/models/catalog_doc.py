
from __future__ import annotations

from pydantic import BaseModel


class _Doc(BaseModel):
    """Base for every index shape: unknown fields are ignored, not refused.

    See this module's docstring for why ignoring is the safe direction
    for a signed, versioned document fetched from a server that ships on
    its own schedule, and why every one of these is FROZEN.
    """

    model_config = {"extra": "ignore", "frozen": True}
