
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Set

from src.cplugs.sdk.safe_io import atomic_write_text
from src.cplugs.save.engine import constants as C

_POINT_RE = re.compile(r"^\d{8}T\d{6}Z-[a-z]+(-\d+)?$")


class InvalidIdError(ValueError):
    pass


def check_point_id(value: str) -> str:
    if isinstance(value, str) and _POINT_RE.match(value):
        return value
    raise InvalidIdError(f"not a valid restore point id: {value!r}")


def new_point_id(reason: str, now: datetime, taken: Set[str]) -> str:
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{stamp}-{reason}"
    candidate, n = base, 1
    while candidate in taken:
        n += 1
        candidate = f"{base}-{n}"
    return candidate


def temp_name(prefix: str = C.TEMP_PREFIX) -> str:
    return f"{prefix}{os.getpid()}-{uuid.uuid4().hex[:10]}"


def fsync_path(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True))
