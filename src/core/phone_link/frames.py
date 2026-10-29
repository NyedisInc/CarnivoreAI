
from __future__ import annotations

import struct
from typing import Tuple

OPEN, DATA, CLOSE, WINDOW, REAUTH, TRUST = 1, 2, 3, 4, 5, 6
FRAME_TYPES = (OPEN, DATA, CLOSE, WINDOW, REAUTH, TRUST)
INITIAL_WINDOW = 256 * 1024
MAX_PAYLOAD = 64 * 1024
MAX_REAUTH_PAYLOAD = 8 * 1024

REASON_NORMAL, REASON_ERROR, REASON_LIMIT, REASON_BREAKER, REASON_IDLE = 0, 1, 2, 3, 4

_HEADER = struct.Struct(">BI")


class FrameError(ValueError):
    pass


def pack(kind: int, stream: int, payload: bytes = b"") -> bytes:
    return _HEADER.pack(kind, stream) + payload


def unpack(raw: bytes) -> Tuple[int, int, bytes]:
    if len(raw) < _HEADER.size:
        raise FrameError("short frame")
    kind, stream = _HEADER.unpack_from(raw)
    payload = raw[_HEADER.size:]
    if kind not in FRAME_TYPES:
        raise FrameError("unknown frame type")
    if kind == WINDOW and len(payload) != 4:
        raise FrameError("window frame must carry a u32")
    return kind, stream, payload


def window_payload(credit: int) -> bytes:
    return struct.pack(">I", credit)


def window_credit(payload: bytes) -> int:
    return struct.unpack(">I", payload)[0]
