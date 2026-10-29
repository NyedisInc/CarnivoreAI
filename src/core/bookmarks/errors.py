
from __future__ import annotations
from src.core.sessions import errors as session_errors


class BookmarkError(Exception):

    status: int = 400
    code: str = "bookmark_error"


class TranscriptUnavailable(BookmarkError):

    status = 409
    code = "transcript_unavailable"


class TranscriptChanged(BookmarkError):

    status = 409
    code = "transcript_changed"


class EntryNotFound(BookmarkError):

    status = 404
    code = "entry_not_found"


class BookmarkNotFound(BookmarkError):

    status = 404
    code = "bookmark_not_found"


class SessionNotFound(BookmarkError, session_errors.SessionNotFound):

    status = 404
    code = "session_not_found"


class NotClaudeSession(BookmarkError):

    status = 409
    code = "not_claude"


class NoConversation(BookmarkError):

    status = 409
    code = "no_conversation"


class RewindRefused(BookmarkError):

    status = 409
    code = "rewind_refused"

    def __init__(self, message: str, *, code: str = "rewind_refused", status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
