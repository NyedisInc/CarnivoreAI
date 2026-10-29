
from __future__ import annotations

from typing import Tuple

ENDED_CLEAR: str = "clear"
ENDED_RESET: str = "reset"
ENDED_NEW: str = "new"
ENDED_FORK: str = "fork"
ENDED_SWITCH: str = "switch"

CLEAR_FAMILY: Tuple[str, ...] = (ENDED_CLEAR, ENDED_RESET, ENDED_NEW)

CLEAR_COMMANDS: dict = {"/clear": ENDED_CLEAR, "/reset": ENDED_RESET, "/new": ENDED_NEW}

HEAD_BYTES: int = 65536
HEAD_RECORDS: int = 40
FIRST_PROMPT_CHARS: int = 200
