
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import Depends

from src.cplugs.sdk import old_names

PREFIX = "/cplugs/huddle"
RETIRED: List[str] = [
    "POST /tell",
    "POST /lists/{key}/tell",
    "PUT /lists/{key}/tell-target",
    "GET /tell-queue",
    "POST /tell-queue/flush",
]
old_names.declare(old_names.KIND_ROUTE, [f"{entry.split(' ', 1)[0]} {PREFIX}{entry.split(' ', 1)[1]}" for entry in RETIRED])


def retired(method: str, path: str) -> Dict[str, Any]:
    if f"{method} {path}" not in RETIRED:
        raise ValueError(f"{method} {path} is not a declared retired route")
    name = f"{method} {PREFIX}{path}"

    def count() -> None:
        old_names.note(old_names.KIND_ROUTE, name)

    return {"dependencies": [Depends(count)], "include_in_schema": False}
