
from __future__ import annotations

from typing import Any, Dict, Optional


class BoardError(Exception):

    status = 400
    code = "reviewboard_error"

    def __init__(self, message: str, *, extra: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.extra = extra or {}


class NoRoot(BoardError):

    status = 409
    code = "reviewboard_no_root"

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message, extra={"reason": reason})
        self.reason = reason


class NoTaskManager(BoardError):

    status = 409
    code = "reviewboard_no_task_manager"


class BoardNotFound(BoardError):

    status = 404
    code = "reviewboard_not_found"


class TaskNotFound(BoardError):

    status = 404
    code = "reviewboard_no_task"


class BoardExists(BoardError):

    status = 409
    code = "reviewboard_exists"


class ReadOnlyBoard(BoardError):
    """The board is invalid or made by a newer Carnivore: it is shown, never written."""

    status = 409
    code = "reviewboard_read_only"


class BadRequest(BoardError):

    status = 422
    code = "reviewboard_invalid"


class StaleSidecar(BoardError):
    """``base_etag`` is not the sidecar's current etag. ``extra`` carries the current ``etag`` and ``sidecar``; nothing was written."""

    status = 409
    code = "reviewboard_stale"


class Unlinked(BoardError):

    status = 409
    code = "reviewboard_unlinked"


class DraftStale(BoardError):

    status = 409
    code = "reviewboard_draft_stale"


class RoundNotFound(BoardError):

    status = 404
    code = "reviewboard_no_round"


class NotScratch(BoardError):

    status = 409
    code = "reviewboard_not_scratch"


class TooLarge(BoardError):

    status = 413
    code = "reviewboard_too_large"


class LengthRequired(BoardError):

    status = 411
    code = "reviewboard_length_required"


class ScratchBoard(BoardError):

    status = 409
    code = "reviewboard_scratch_board"


class TaskManagerRefused(BoardError):

    status = 409
    code = "reviewboard_task_manager_refused"


class StoreFailed(BoardError):
    """A file of an attach could not be written to the task's folder; nothing was attached (``attachments.py``)."""

    status = 500
    code = "reviewboard_store_failed"


class NotLive(BoardError):

    status = 409
    code = "reviewboard_not_live"
