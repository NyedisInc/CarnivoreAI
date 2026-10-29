
from __future__ import annotations

import re
from datetime import datetime
from typing import List

MAX_READ_RUN_IDS = 500

_SEEN_AT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")
_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def check_seen_at(value: str) -> str:
    if not _SEEN_AT.match(value):
        raise ValueError("must be an ISO 8601 UTC time ending in Z")
    try:
        datetime.fromisoformat(value[:-1])
    except ValueError:
        raise ValueError("must be a real calendar time") from None
    return value


def check_read_run_ids(value: List[str]) -> List[str]:
    if len(value) > MAX_READ_RUN_IDS:
        raise ValueError(f"at most {MAX_READ_RUN_IDS} run ids")
    if len(set(value)) != len(value):
        raise ValueError("run ids must be unique")
    if not all(_RUN_ID.match(run_id) for run_id in value):
        raise ValueError("a run id is 1 to 80 letters, digits, underscores or hyphens")
    return value
