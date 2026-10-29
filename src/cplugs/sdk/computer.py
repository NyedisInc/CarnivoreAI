
from __future__ import annotations

import re
from typing import Optional

_BAD = re.compile(r"[^A-Za-z0-9._-]")


def local_computer() -> Optional[str]:
    from src.core.federation.discovery import local_host_name  # noqa: PLC0415

    name = _BAD.sub("-", local_host_name().strip()).strip("-._")[:64]
    return name or None
