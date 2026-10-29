
from __future__ import annotations

from typing import Any, Dict, List, Optional


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


class NotAttacher(BoardError):

    status = 403
    code = "reviewboard_not_attacher"


class BytesNotRemoved(BoardError):

    status = 503
    code = "reviewboard_bytes_not_removed"


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

    status = 409
    code = "reviewboard_read_only"


class BadRequest(BoardError):

    status = 422
    code = "reviewboard_invalid"


class StaleSidecar(BoardError):

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


class FileTypeRefused(BoardError):

    status = 415
    code = "reviewboard_file_type_refused"

    def __init__(self, message: str, *, reason: str, file: str, extension: Optional[str] = None) -> None:
        super().__init__(message, extra={"reason": reason, "file": file, **({"extension": extension} if extension else {})})


class SecretInFile(BoardError):

    status = 422
    code = "reviewboard_file_has_secret"

    def __init__(self, message: str, *, files: List[Dict[str, Any]]) -> None:
        super().__init__(message, extra={"files": files})


class UnscannableFile(BoardError):

    status = 422
    code = "reviewboard_file_unscannable"

    def __init__(self, message: str, *, files: List[Dict[str, Any]]) -> None:
        super().__init__(message, extra={"files": files})


class AttachmentNotFound(BoardError):

    status = 404
    code = "reviewboard_no_attachment"


class StoreFailed(BoardError):

    status = 500
    code = "reviewboard_store_failed"


class NotLive(BoardError):

    status = 409
    code = "reviewboard_not_live"
