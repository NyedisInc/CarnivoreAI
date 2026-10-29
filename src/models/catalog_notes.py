
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class NoteWriteRequest(BaseModel):
    """``POST /catalog/items/{item_id}/note``: the note being sent.

    Fields:
        text: the words. A non-string body is refused by FastAPI before
            this ever reaches the handler; empty and over-length are the
            hosted api's job, exactly as it is for a rating's text.
    """

    text: str


class NoteSentResponse(BaseModel):
    """What a successful send answers, relayed field for field.

    THE APP KEEPS NO COPY OF WHAT WAS SENT. Only the id the note is about
    and when the hosted api recorded it come back; the text itself is
    never echoed, so a screen cannot show it again after sending even by
    accident.

    Fields:
        item_id: the id the hosted api echoed back.
        created_at: ISO 8601 UTC string, the hosted api's own clock.
    """

    item_id: Optional[str] = None
    created_at: Optional[str] = None
