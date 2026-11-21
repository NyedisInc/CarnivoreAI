
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from typing import Iterator

_OPEN: Counter[str] = Counter()


@contextmanager
def serving(install_key: str) -> Iterator[None]:
    _OPEN[install_key] += 1
    try:
        yield
    finally:
        _OPEN[install_key] -= 1
        if _OPEN[install_key] <= 0:
            del _OPEN[install_key]


def is_serving(install_key: str) -> bool:
    return _OPEN.get(install_key, 0) > 0
