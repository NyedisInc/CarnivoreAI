
from __future__ import annotations


class LabError(Exception):

    status = 400
    code = "lab_error"


class CaptureUnavailable(LabError):

    status = 503
    code = "capture_unavailable"


class CaptureBusy(LabError):

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

    status = 409
    code = "draft_exists"


class NoCheckout(LabError):

    status = 503
    code = "no_checkout"


class BuildBusy(LabError):

    status = 409
    code = "build_busy"


class SessionUnavailable(LabError):

    status = 502
    code = "session_unavailable"
