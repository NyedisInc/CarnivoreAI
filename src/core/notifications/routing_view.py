
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class QuietHours:

    start: str
    end: str


@dataclass(frozen=True)
class DestinationView:

    id: str
    kind: str
    name: str
    enabled: bool
    scope: str
    config: Mapping[str, object]
    details: bool = False
    away: bool = False
    quiet: Optional[QuietHours] = None
    reminder_minutes: Optional[int] = None
    projects: tuple[str, ...] = ()


@runtime_checkable
class RoutingView(Protocol):

    revision: int
    paused: bool

    def destinations(self) -> Sequence[DestinationView]:
        ...

    def is_ticked(self, column: str, type_id: str) -> bool:
        ...


class RoutingWriter(Protocol):

    async def disable_locally(self, dest_id: str, reason: str) -> None:
        ...


@dataclass(frozen=True)
class DestinationStatus:

    last_ok_ts: Optional[float] = None
    last_failure_ts: Optional[float] = None
    last_failure: Optional[str] = None
    consecutive_permanent_failures: int = 0
    disabled_reason: Optional[str] = None


_view_provider: Optional[Callable[[], RoutingView]] = None
_writer: Optional[RoutingWriter] = None
_status_provider: Optional[Callable[[], Mapping[str, DestinationStatus]]] = None


def install_routing(view_provider: Callable[[], RoutingView], writer: RoutingWriter) -> None:
    global _view_provider, _writer
    _view_provider = view_provider
    _writer = writer


def uninstall_routing() -> None:
    global _view_provider, _writer, _status_provider
    _view_provider = None
    _writer = None
    _status_provider = None


def current_view() -> Optional[RoutingView]:
    """The current view, or None when routing is not installed."""
    provider = _view_provider
    return provider() if provider is not None else None


def routing_writer() -> Optional[RoutingWriter]:
    return _writer


def install_status_provider(fn: Callable[[], Mapping[str, DestinationStatus]]) -> None:
    global _status_provider
    _status_provider = fn


def current_statuses() -> Mapping[str, DestinationStatus]:
    provider = _status_provider
    return provider() if provider is not None else {}
