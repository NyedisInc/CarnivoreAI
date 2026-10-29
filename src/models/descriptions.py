
from typing import Optional

from pydantic import BaseModel, Field

from src.core.descriptions.limits import LONG_DESCRIPTION_MAX, SHORT_DESCRIPTION_MAX


class SessionDescriptionRequest(BaseModel):
    """Set a session's short and/or long description. Omit a field to keep it; an empty string clears it."""

    short_description: Optional[str] = Field(
        None, max_length=SHORT_DESCRIPTION_MAX,
        description="One line, at most 120 characters: what this session is doing",
    )
    long_description: Optional[str] = Field(
        None, max_length=LONG_DESCRIPTION_MAX,
        description="At most 2000 characters: what this session is for, its scope and who it works with",
    )


class SessionDescriptionResponse(BaseModel):
    """The committed descriptions, read back after the write."""

    session_uuid: str
    session_row_id: int
    short_description: Optional[str] = None
    long_description: Optional[str] = None
