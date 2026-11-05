
from __future__ import annotations

from typing import Callable, Dict, List, Optional

import structlog

logger = structlog.get_logger()

Observer = Callable[[str, bytes], None]


class OutputTap:

    def __init__(self) -> None:
        self._every: List[Observer] = []
        self._by_session: Dict[str, List[Observer]] = {}

    def add(self, observer: Observer, session_id: Optional[str] = None) -> None:
        if session_id is None:
            self._every.append(observer)
        else:
            self._by_session.setdefault(session_id, []).append(observer)

    def remove(self, observer: Observer, session_id: Optional[str] = None) -> None:
        bucket = self._every if session_id is None else self._by_session.get(session_id)
        if bucket is None:
            return
        try:
            bucket.remove(observer)
        except ValueError:
            return
        if session_id is not None and not bucket:
            del self._by_session[session_id]

    def observer_count(self, session_id: Optional[str] = None) -> int:
        if session_id is None:
            return len(self._every)
        return len(self._every) + len(self._by_session.get(session_id, ()))

    def emit(self, session_id: str, data: bytes) -> None:
        if not self._every and not self._by_session:
            return
        if self._every:
            self._run(self._every, None, session_id, data)
        if self._by_session:
            bucket = self._by_session.get(session_id)
            if bucket:
                self._run(bucket, session_id, session_id, data)

    def _run(self, bucket: List[Observer], key: Optional[str], session_id: str, data: bytes) -> None:
        for observer in list(bucket):
            try:
                observer(session_id, data)
            except Exception as exc:  # noqa: BLE001
                self.remove(observer, key)
                logger.warning("output_tap_observer_disabled", session_id=session_id,
                               observer=getattr(observer, "__qualname__", repr(observer)),
                               error=str(exc), error_type=type(exc).__name__)


TAP = OutputTap()
