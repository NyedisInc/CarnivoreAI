
from __future__ import annotations

from typing import Optional, TypedDict


class FileDeletion(TypedDict):

    deleted: bool
    shared: bool
    redacted: bool
    failed: bool
    reason: Optional[str]
