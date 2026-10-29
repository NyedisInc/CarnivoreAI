
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict


class NameLocks:

    def __init__(self) -> None:
        self._locks: Dict[str, asyncio.Lock] = {}
        self._users: Dict[str, int] = {}

    @asynccontextmanager
    async def hold(self, name: str) -> AsyncIterator[None]:
        lock = self._locks.setdefault(name, asyncio.Lock())
        self._users[name] = self._users.get(name, 0) + 1
        try:
            async with lock:
                yield
        finally:
            self._users[name] -= 1
            if self._users[name] == 0:
                del self._users[name]
                del self._locks[name]

    def held_names(self) -> int:
        return len(self._locks)

