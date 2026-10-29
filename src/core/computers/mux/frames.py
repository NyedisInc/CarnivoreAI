
from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass

PROTOCOL_VERSION = 1
MAX_PAYLOAD = 16384
MAX_HELLO = 4096
MAX_SERVICE = 32
HEADER = struct.Struct(">BII")

HELLO, OPEN, DATA, FIN, RST, WINDOW, PING, PONG, GOAWAY = range(9)
TYPE_NAMES = {HELLO: "hello", OPEN: "open", DATA: "data", FIN: "fin", RST: "rst", WINDOW: "window",
              PING: "ping", PONG: "pong", GOAWAY: "goaway"}

RST_NORMAL, RST_ERROR, RST_LIMIT, RST_UNAVAILABLE, RST_UNKNOWN = range(5)
GO_NORMAL, GO_PROTOCOL, GO_VERSION, GO_REPLACED, GO_REMOVED = range(5)

_CONNECTION_TYPES = frozenset({HELLO, PING, PONG, GOAWAY})


class FrameError(Exception):
    pass


@dataclass(frozen=True)
class Frame:

    type: int
    stream: int
    payload: bytes


def pack(ftype: int, stream: int, payload: bytes = b"") -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("payload over the frame cap")
    return HEADER.pack(ftype, stream, len(payload)) + payload


def pack_u8(value: int) -> bytes:
    return bytes((value,))


def pack_u32(value: int) -> bytes:
    return struct.pack(">I", value)


def validate(frame: Frame) -> None:
    t, s, n = frame.type, frame.stream, len(frame.payload)
    if t not in TYPE_NAMES:
        raise FrameError("unknown frame type")
    if t in _CONNECTION_TYPES and s != 0:
        raise FrameError("connection frame on a stream")
    if t not in _CONNECTION_TYPES and s == 0:
        raise FrameError("stream frame on stream 0")
    if t == HELLO and n > MAX_HELLO:
        raise FrameError("hello too large")
    if t == OPEN and not 1 <= n <= MAX_SERVICE:
        raise FrameError("bad service name length")
    if t in (PING, PONG) and n != 8:
        raise FrameError("ping payload must be 8 bytes")
    if t in (RST, GOAWAY) and n != 1:
        raise FrameError("reason payload must be 1 byte")
    if t == WINDOW and n != 4:
        raise FrameError("window payload must be 4 bytes")
    if t == FIN and n:
        raise FrameError("fin carries no payload")


async def read_frame(reader: asyncio.StreamReader) -> Frame:
    head = await reader.readexactly(HEADER.size)
    ftype, stream, length = HEADER.unpack(head)
    if length > MAX_PAYLOAD:
        raise FrameError("frame over the length cap")
    payload = await reader.readexactly(length) if length else b""
    frame = Frame(ftype, stream, payload)
    validate(frame)
    return frame
