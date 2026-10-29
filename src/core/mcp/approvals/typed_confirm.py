
from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

TYPED: ContextVar[Optional[str]] = ContextVar("approval_typed_answer", default=None)


class ConfirmationMismatch(Exception):
    pass


def check(expected: str, typed: Optional[str]) -> None:
    if expected and typed != expected:
        raise ConfirmationMismatch("type the exact name shown on the card to confirm")


def typed_answer() -> Optional[str]:
    return TYPED.get()
