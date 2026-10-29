
from __future__ import annotations

from typing import Callable, Optional

from src.core.resource_push import notifier
from src.core.resource_push.topics import CLIENT_BUILD


class ClientBuildWatch:

    def __init__(self, read_key: Callable[[], str]) -> None:
        self._read_key = read_key
        self._last: Optional[str] = None

    def check(self) -> bool:
        key = self._read_key()
        if not key:
            return False
        previous, self._last = self._last, key
        if previous is None or previous == key:
            return False
        notifier.notify(CLIENT_BUILD)
        return True
