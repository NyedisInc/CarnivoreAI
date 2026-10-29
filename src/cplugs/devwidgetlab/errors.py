
from __future__ import annotations


class LabError(Exception):

    status = 400
    code = "lab_error"


class CaptureUnavailable(LabError):

    status = 503
    code = "capture_unavailable"


class CaptureBusy(LabError):
    """A capture is already running; the harness is built and driven one at a time."""

    status = 409
    code = "capture_busy"


class CaptureTimeout(LabError):

    status = 504
    code = "capture_timeout"


class DraftInvalid(LabError):

    status = 400
    code = "draft_invalid"


class DraftNotFound(LabError):

    status = 404
    code = "draft_not_found"


class DraftExists(LabError):
    """A draft folder with that slug already exists (or the id belongs to a shipped widget)."""

    status = 409
    code = "draft_exists"


class NoCheckout(LabError):

    status = 503
    code = "no_checkout"


class BuildBusy(LabError):
    """A draft build is already running; builds run one at a time."""

    status = 409
    code = "build_busy"


class SessionUnavailable(LabError):
    """The draft could not be handed to a Claude session (the session grant is missing, or the create route refused)."""

    status = 502
    code = "session_unavailable"
