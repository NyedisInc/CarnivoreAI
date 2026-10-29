
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator


@contextmanager
def lend_name_read_connection(manager: Any) -> Iterator[None]:
    if getattr(manager._borrowed, "conn", None) is not None:
        yield
        return
    conn = manager._name_read_connection()[0]
    manager._borrowed.conn = conn
    try:
        yield
    finally:
        manager._borrowed.conn = None
