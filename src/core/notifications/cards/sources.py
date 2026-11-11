
from __future__ import annotations

from typing import Any, Dict, Optional, Protocol


class Sources(Protocol):

    async def dialog(self, session_id: str) -> Optional[Dict[str, Any]]:
        ...

    def details_on(self, dest_id: str) -> bool:
        ...

    async def extra(self, event: Any) -> Dict[str, Any]:
        ...


class _None:

    async def dialog(self, session_id: str) -> Optional[Dict[str, Any]]:
        return None

    def details_on(self, dest_id: str) -> bool:
        return True

    async def extra(self, event: Any) -> Dict[str, Any]:
        return {}


_current: Sources = _None()


def install(sources: Optional[Sources]) -> None:
    global _current
    _current = sources if sources is not None else _None()


def current() -> Sources:
    return _current
