
from __future__ import annotations

import json
import os
import zlib
from pathlib import Path
from typing import Any, Dict

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
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as handle:
            handle.write(blob)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
