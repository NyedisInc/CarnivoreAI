
from __future__ import annotations

import base64
import json
import math
from typing import Any, Iterable, Iterator, Union


class RawText(bytes):
    pass


def text_factory(raw: bytes) -> Union[str, RawText]:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return RawText(raw)


def dumps(obj: Any) -> bytes:
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return text.encode("utf-8") + b"\n"


def jsonl(records: Iterable[Any]) -> Iterator[bytes]:
    for record in records:
        yield dumps(record)


def encode_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int)) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            raise ValueError("NaN cannot be stored in a crate (SQLite never returns it)")
        if math.isinf(value):
            return {"$f": "inf" if value > 0 else "-inf"}
        return value
    if isinstance(value, RawText):
        return {"$t64": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"$b64": base64.b64encode(bytes(value)).decode("ascii")}
    raise ValueError(f"a {type(value).__name__} is not a SQLite value")


def decode_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    if len(value) != 1:
        raise ValueError("an encoded value is an object with exactly one key")
    (key, inner), = value.items()
    if not isinstance(inner, str):
        raise ValueError(f"the {key} form holds a string")
    try:
        if key == "$b64":
            return base64.b64decode(inner, validate=True)
        if key == "$t64":
            return RawText(base64.b64decode(inner, validate=True))
    except ValueError as exc:
        raise ValueError(f"bad base64 in a {key} value") from exc
    if key == "$f" and inner in ("inf", "-inf"):
        return math.inf if inner == "inf" else -math.inf
    raise ValueError(f"unknown encoded value form {key!r}")


def loads(data: bytes) -> Any:

    def _refuse(token: str) -> Any:
        raise ValueError(f"the JSON constant {token} is not allowed in a crate")

    try:
        return json.loads(data.decode("utf-8"), parse_constant=_refuse)
    except RecursionError:
        raise ValueError("the JSON is nested too deeply to parse") from None
