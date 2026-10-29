
from __future__ import annotations

import re
from typing import Optional, Pattern, Union

PERMISSION_TAIL_LINES: int = 60

PERMISSION_DIALOG_MARKERS: tuple[Union[str, Pattern[str]], ...] = (
    re.compile(r"^\s*Do you want to .{0,120}\?\s*$", re.M),
    re.compile(r"^\s*❯\s*1\.\s*Yes\b", re.M),
    "Esc to cancel · Tab to amend",
)


def detect_permission_dialog(tail: Optional[str]) -> Optional[bool]:
    if tail is None:
        return None
    for marker in PERMISSION_DIALOG_MARKERS:
        if isinstance(marker, str):
            if marker in tail:
                return True
        elif marker.search(tail):
            return True
    return False
