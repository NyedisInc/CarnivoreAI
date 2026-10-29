
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Optional, Protocol, runtime_checkable

import structlog

logger = structlog.get_logger(__name__)

ORIGIN_LOCAL = "local"
ORIGIN_PEER = "peer"

SEVERITY_INFO = "info"
SEVERITY_WARN = "warn"
SEVERITY_ERROR = "error"


@dataclass(frozen=True)
class NotifyEvent:

    type_id: str
    kind: str
    title: str
    ts: float
    session_ref: str = ""
    severity: str = SEVERITY_INFO
    link: Optional[str] = None
    instance_key: str = ""
    toast_id: Optional[str] = None
    toast_version: Optional[int] = None
    session_id: Optional[str] = None
    tmux_name: Optional[str] = None
    project: str = ""
    computer: str = ""
    origin: str = ORIGIN_LOCAL
    details: Optional[str] = None
    open_item: bool = False
    session_uuid: Optional[str] = None
    copy_variant: str = ""
    copy_fields: tuple = ()


class FailureClass(str, Enum):

    TIMEOUT = "timeout"
    NETWORK = "network"
    SERVER = "server"
    RATE_LIMITED = "rate_limited"
    AUTH = "auth"
    GONE = "gone"
    INVALID = "invalid"
    BLOCKED = "blocked"
    KEYCHAIN_LOCKED = "keychain_locked"
    SECRET_MISSING = "secret_missing"
    PRIVATE_OFF = "private_off"
    PLAIN_HTTP_OFF = "plain_http_off"
    ORIGIN_CHANGED = "origin_changed"


RETRYABLE: frozenset = frozenset(
    {FailureClass.TIMEOUT, FailureClass.NETWORK, FailureClass.SERVER, FailureClass.RATE_LIMITED}
)

NOT_COUNTED: frozenset = frozenset({
    FailureClass.KEYCHAIN_LOCKED, FailureClass.SECRET_MISSING, FailureClass.PRIVATE_OFF, FailureClass.PLAIN_HTTP_OFF,
    FailureClass.ORIGIN_CHANGED,
})


@dataclass(frozen=True)
class DeliveryResult:

    ok: bool
    failure: Optional[FailureClass] = None
    status_code: Optional[int] = None
    retry_after: Optional[float] = None
    detail: str = ""

    @property
    def retryable(self) -> bool:
        return self.failure in RETRYABLE


@runtime_checkable
class Sender(Protocol):

    async def send(
        self, event: NotifyEvent, config: Mapping[str, Any], secrets: Mapping[str, Any]
    ) -> DeliveryResult:
        ...


Sink = Callable[[NotifyEvent], None]

_sink: Optional[Sink] = None


def install_sink(fn: Sink) -> None:
    global _sink
    _sink = fn


def uninstall_sink() -> None:
    global _sink
    _sink = None


def sink_installed() -> bool:
    return _sink is not None


def emit(event: NotifyEvent) -> None:
    sink = _sink
    if sink is None:
        return
    try:
        sink(event)
    except Exception as exc:  # noqa: BLE001
        logger.warning("notify_emit_sink_failed", type_id=event.type_id, error_type=type(exc).__name__)
