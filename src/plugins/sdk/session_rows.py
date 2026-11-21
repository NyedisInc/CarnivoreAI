
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class SessionRowsUnreadable(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredRow:

    project_id: Optional[int]
    archived: bool
