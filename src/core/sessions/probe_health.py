
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
        """The socket to key rows on: the probed one, else the configured one.

        Description: THE PROBE WINS OVER SETTINGS WHEN THE TWO DISAGREE,
          and that is the whole reason this is a method rather than a raw
          settings read. A row is WRITTEN keyed on the socket the adopt
          path saw and is READ back by ``owned_instances`` keyed on
          whatever this returns; if those two ever differ, the badge is
          answered from a socket nothing was written to and every adopted
          session reads as external. Following the socket the probe was
          ACTUALLY bound to keeps writer and reader on the same key AND
          keeps that key equal to reality. In production the values are
          identical; they diverge only where a harness pins a backend to
          a dedicated socket, and there following the pin is exactly
          right.
        Inputs: configured (str) - the already-resolved settings value,
          passed in rather than read here so this class stays free of a
          config import and needs no double to test.
        Output: str.
        Example: recorder.socket_name(configured="cloude")  # 'cloude'
        """
        if self._socket:
            return str(self._socket)
        return configured
