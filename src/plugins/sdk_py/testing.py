
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .plugin import HostError, Plugin


class FakeHost:

    def __init__(self, responses: Dict[str, Any] = None) -> None:
        self.responses = responses or {}
        self.calls: List[Tuple[str, Dict[str, Any]]] = []

    async def __call__(self, method: str, params: Dict[str, Any]) -> Any:
        self.calls.append((method, params))
        answer = self.responses.get(method, {})
        if isinstance(answer, HostError):
            raise answer
        return answer


def attach(plugin: Plugin, host: FakeHost) -> Plugin:
    from .plugin import Host  # noqa: PLC0415

    plugin.host = Host(host)
    return plugin
