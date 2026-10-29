
from __future__ import annotations

import sqlite3
import struct
import zlib
from typing import Any, Optional, Union

BODY_FRAME_MAGIC: bytes = b"CBZ1"

_COUNT_STRUCT: struct.Struct = struct.Struct("<Q")

BODY_FRAME_HEADER_BYTES: int = len(BODY_FRAME_MAGIC) + _COUNT_STRUCT.size

BODY_COMPRESSION_LEVEL: int = 6

SQL_FN_BODY_TEXT: str = "cloude_body_text"
SQL_FN_BODY_CHARS: str = "cloude_body_chars"


class BodyCodecError(ValueError):
    """A stored body could not be interpreted as either shape.

    Description: raised rather than returning None or an empty string,
      because a body that cannot be read is a COULD NOT EVALUATE and a
      caller that receives "" will render it as an empty message. The
      message names what was found, never the body's content.
    Inputs: standard ValueError arguments.
    Output: an exception instance.
    """


def is_compressed(value: Any) -> bool:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value[:len(BODY_FRAME_MAGIC)]) == BODY_FRAME_MAGIC
    return False


def encode_body(text: str) -> bytes:
    if not isinstance(text, str):
        raise TypeError(
            f"encode_body needs a str; got {type(text).__name__}"
        )
    payload = zlib.compress(text.encode("utf-8"), BODY_COMPRESSION_LEVEL)
    return BODY_FRAME_MAGIC + _COUNT_STRUCT.pack(len(text)) + payload


def decode_body(value: Union[str, bytes, bytearray, memoryview]) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise BodyCodecError(
            f"body_json held {type(value).__name__}, which is neither text "
            f"nor a stored body frame"
        )
    raw = bytes(value)
    if not is_compressed(raw):
        raise BodyCodecError(
            f"body_json held a {len(raw)} byte blob that does not carry the "
            f"{BODY_FRAME_MAGIC!r} frame magic; refusing to guess at it"
        )
    try:
        text = zlib.decompress(raw[BODY_FRAME_HEADER_BYTES:]).decode("utf-8")
    except (zlib.error, UnicodeDecodeError) as exc:
        raise BodyCodecError(
            f"a framed body would not inflate: {type(exc).__name__}: {exc}"
        ) from exc
    declared = _framed_char_count(raw)
    if declared != len(text):
        raise BodyCodecError(
            f"a framed body declares {declared} characters and inflated to "
            f"{len(text)}; the frame and its payload disagree"
        )
    return text


def body_chars(value: Union[str, bytes, bytearray, memoryview]) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        if is_compressed(raw):
            return _framed_char_count(raw)
    raise BodyCodecError(
        f"body_json held {type(value).__name__} with no readable length; "
        f"refusing to report a count nothing measured"
    )


def _framed_char_count(raw: bytes) -> int:
    if len(raw) < BODY_FRAME_HEADER_BYTES:
        raise BodyCodecError(
            f"a stored body frame is {len(raw)} bytes, shorter than its "
            f"{BODY_FRAME_HEADER_BYTES} byte header"
        )
    start = len(BODY_FRAME_MAGIC)
    return int(_COUNT_STRUCT.unpack_from(raw, start)[0])


def _sql_body_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    return decode_body(value)


def _sql_body_chars(value: Any) -> Optional[int]:
    if value is None:
        return None
    return body_chars(value)


def register_body_functions(conn: sqlite3.Connection) -> None:
    conn.create_function(
        SQL_FN_BODY_TEXT, 1, _sql_body_text, deterministic=True,
    )
    conn.create_function(
        SQL_FN_BODY_CHARS, 1, _sql_body_chars, deterministic=True,
    )
