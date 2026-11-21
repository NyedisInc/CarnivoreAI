
from __future__ import annotations

import contextlib
import contextvars
from typing import Iterator, Optional

HEADER = "X-Carnivore-Tool-Timeout"
ASSUMED_S = 60
HEADROOM_S = 25
FLOOR_S = 50.0
CAP_S = 600.0

_budget: contextvars.ContextVar[float] = contextvars.ContextVar(
    "mcp_call_budget_s", default=FLOOR_S
)


def from_header(value: Optional[str]) -> float:
    declared = ASSUMED_S
    try:
        parsed = int(str(value).strip())
        if 1 <= parsed <= 86400:
            declared = parsed
    except (TypeError, ValueError):
        pass
    return max(FLOOR_S, min(CAP_S, float(declared - HEADROOM_S)))


@contextlib.contextmanager
def using(seconds: float) -> Iterator[None]:
    token = _budget.set(float(seconds))
    try:
        yield
    finally:
        _budget.reset(token)


def current() -> float:
    return _budget.get()
