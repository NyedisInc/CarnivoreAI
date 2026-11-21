
from __future__ import annotations

from typing import Optional


class Availability:

    def __init__(self) -> None:
        self.reason: Optional[str] = None

    def set(self, reason: str) -> None:
        self.reason = reason

    def clear(self) -> None:
        self.reason = None

    @property
    def ok(self) -> bool:
        return self.reason is None


AVAILABILITY = Availability()
