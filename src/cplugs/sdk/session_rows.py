
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class SessionRowsUnreadable(RuntimeError):
    """The session rows could not be read: an absence decided from this read would be a guess, so the caller decides nothing."""


@dataclass(frozen=True)
class StoredRow:

    project_id: Optional[int]
    archived: bool
