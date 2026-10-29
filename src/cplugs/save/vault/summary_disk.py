
from __future__ import annotations

import json
import zlib
from pathlib import Path
from typing import Any, Dict
from src.cplugs.sdk.safe_io import atomic_write_bytes

FORMAT = 1

_COMPRESS_LEVEL = 1


class SummaryStoreError(Exception):
    pass


def dump(units: Dict[str, Any]) -> bytes:
    text = json.dumps({"v": FORMAT, "units": units}, separators=(",", ":"))
    return zlib.compress(text.encode("utf-8"), _COMPRESS_LEVEL)


def load(blob: bytes) -> Dict[str, Any]:
    try:
        data = json.loads(zlib.decompress(blob).decode("utf-8"))
    except (zlib.error, ValueError) as exc:
        raise SummaryStoreError(f"undecodable: {exc}") from exc
    if not isinstance(data, dict) or data.get("v") != FORMAT or not isinstance(data.get("units"), dict):
        raise SummaryStoreError("unknown format")
    return data["units"]


def write_atomic(path: Path, blob: bytes) -> None:
    atomic_write_bytes(path, blob)
