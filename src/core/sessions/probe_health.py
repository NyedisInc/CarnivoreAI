
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProbeHealth:

    ok: Optional[bool]
    reason: Optional[str] = None
    detail: Optional[str] = None


class ProbeHealthRecorder:

    def __init__(self) -> None:
        self._health: ProbeHealth = ProbeHealth(ok=None)
        self._socket: Optional[str] = None

    @property
    def health(self) -> ProbeHealth:
        return self._health

    @property
    def socket(self) -> Optional[str]:
        return self._socket

    def record_socket(self, socket_name: Optional[str]) -> None:
        self._socket = socket_name

    def record_success(self) -> None:
        self._health = ProbeHealth(ok=True)

    def record_failure(self, *, reason: Optional[str], detail: Optional[str]) -> None:
        self._health = ProbeHealth(ok=False, reason=reason, detail=detail)

    def socket_name(self, configured: str) -> str:
        if self._socket:
            return str(self._socket)
        return configured
