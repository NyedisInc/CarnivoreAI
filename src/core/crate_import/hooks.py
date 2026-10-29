
from __future__ import annotations

from typing import Any, Dict

PHASE_PLANNING = "planning"
PHASE_FILES = "files"
PHASE_ROWS = "rows"
PHASE_POST = "post"
PHASE_CHECKING = "checking"

CP_BEFORE_FILES = "before_files"
CP_AFTER_FILES = "after_files"
CP_BEFORE_COMMIT = "before_commit"
CP_AFTER_ROWS = "after_rows"
CP_AFTER_POST = "after_post"


class ApplyHooks:

    def phase(self, name: str, total: int = 0, files: int = 0) -> None:
        pass

    def add(self, nbytes: int, files: int = 0) -> None:
        pass

    def check(self) -> None:
        pass

    def undo(self, entry: Dict[str, Any]) -> None:
        pass

    def checkpoint(self, name: str) -> None:
        pass
