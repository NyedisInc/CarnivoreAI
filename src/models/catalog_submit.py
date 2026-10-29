
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class SubmissionFileView(BaseModel):
    """One file that would be sent: what it is called and how big it is.

    Fields:
        path: the member path, relative and POSIX spelled, exactly as the
            submission would carry it.
        size: bytes on disk, measured with ``lstat``. Never null in
            practice, because a file that could not be measured becomes a
            refusal instead of a row with a fabricated zero.
    """

    path: str
    size: Optional[int] = None


class SubmissionRefusalView(BaseModel):
    """One reason this folder would not be accepted.

    Fields:
        code: ``submission_invalid``, ``name_reserved``,
            ``scripts_not_supported`` or ``body_too_large``. THE CLIENT
            RENDERS THESE FROM ITS OWN SUBMIT NAMESPACE, because two of
            them mean something different in the shared refusal table.
        detail: the server's own words. Rendered only for
            ``submission_invalid``, which covers a dozen shapes that one
            sentence could not usefully describe.
        path: the member that caused it, or null when the folder as a
            whole did.
    """

    code: str
    detail: Optional[str] = None
    path: Optional[str] = None
