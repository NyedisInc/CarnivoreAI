
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

_ports: Dict[str, Any] = {}
_listeners: List[Callable[[str], None]] = []


def register(name: str, port: Any) -> None:
    _ports[name] = port
    _announce(name)


def unregister(name: str) -> None:
    if _ports.pop(name, None) is not None:
        _announce(name)


def get(name: str) -> Optional[Any]:
    return _ports.get(name)


def subscribe(listener: Callable[[str], None]) -> Callable[[], None]:
    _listeners.append(listener)
    return lambda: _listeners.remove(listener) if listener in _listeners else None


def _announce(name: str) -> None:
    for listener in list(_listeners):
        listener(name)
