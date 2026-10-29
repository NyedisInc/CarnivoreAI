
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ScoutSuggestion(BaseModel):
    """One suggested catalog skill. ``reason`` is plain text, never HTML."""

    item_id: str = Field(..., description="Id of an item in the verified index")
    name: str = Field(..., description="The item's name")
    reason: str = Field(..., description="The agent's short reason, plain text")


class ScoutRequested(BaseModel):
    """What the scout POST did: the prompt was pasted and submitted."""

    pasted_bytes: int
    items_listed: int = Field(..., description="Catalog skills the prompt listed")


class ScoutReply(BaseModel):
    """The scout reply read from the transcript.

    ``state``: ``none`` (no scout asked yet), ``waiting`` (asked, no reply
    yet), ``ready`` (a reply is in; ``suggestions`` may be empty),
    ``not_measured`` (no transcript to read), ``unsupported`` (not Claude).
    """

    state: str
    suggestions: List[ScoutSuggestion] = Field(default_factory=list)
    detail: Optional[str] = None
