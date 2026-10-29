
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from src.core.sessions.ports import SessionManagerSurface


@contextmanager
def lend_name_read_connection(manager: SessionManagerSurface) -> Iterator[None]:
    if getattr(manager._borrowed, "conn", None) is not None:
        yield
        return
    conn = manager._name_read_connection()[0]
    manager._borrowed.conn = conn
    try:
        yield
    finally:
        manager._borrowed.conn = None
        if conn is not None:
            conn.close()
