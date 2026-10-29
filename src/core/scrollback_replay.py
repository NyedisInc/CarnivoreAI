
from __future__ import annotations

import re
from typing import Optional, Tuple

_BARE_LF = re.compile(rb"(?<!\r)\n")


def normalize_replay_newlines(data: bytes) -> bytes:
    if not data:
        return data
    return _BARE_LF.sub(b"\r\n", data)


def with_cursor_restore(
    data: bytes, cursor: Optional[Tuple[int, int]]
) -> bytes:
    if not data or cursor is None:
        return data
    col, row = cursor
    return data + f"\x1b[{row + 1};{col + 1}H".encode("ascii")
