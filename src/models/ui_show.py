
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.core.ui_show import KINDS
from src.core.ui_show.last_window import CLIENT_ID_PATTERN

MAX_ID_LENGTH = 200


class ActivityRequest(BaseModel):
    """``POST /ui/activity``: this window just had user input."""

    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(..., pattern=CLIENT_ID_PATTERN.pattern, description="The browser tab's id (the terminal socket's ?client_id=).")


class ShowRequest(BaseModel):
    """``POST /ui/show``: the item to bring into view in the window used last."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal[KINDS] = Field(..., description="session, file, browser, board, layout or task_manager.")  # type: ignore[valid-type]
    id: Optional[str] = Field(None, min_length=1, max_length=MAX_ID_LENGTH,
                              description="The item's id: a session id, a file or browser row id, a board slug, a layout uuid. Not for task_manager.")
    target_client_id: Optional[str] = Field(None, pattern=CLIENT_ID_PATTERN.pattern,
                                            description="Optional: show in this window (a client id that reported input and is not gone) instead of the window used last.")


class ShowResponse(BaseModel):
    """What a show answers: the pointer's identity, never the target window's id."""

    shown: bool = True
    kind: str
    id: str
    title: str
    seq: int
