
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from src.core.federation.grants import GrantError, decode_public_key
from src.core.relay_identity.device_key import unb64url

SAS_PREFIX = b"carnivore federation v1 pair-sas\x00"
FINISH_PREFIX = b"carnivore federation v1 pair-finish\x00"
SAS_DIGITS = 10
PENDING_TTL_SECONDS = 5 * 60
MAX_PENDING = 8


def compute_sas(key_a: bytes, key_b: bytes, nonce: str) -> str:
    first, second = sorted((key_a, key_b))
    digest = hashlib.sha256(SAS_PREFIX + nonce.encode() + b"\x00" + first + second).digest()
    digits = f"{int.from_bytes(digest[:8], 'big') % 10 ** SAS_DIGITS:0{SAS_DIGITS}d}"
    return f"{digits[:SAS_DIGITS // 2]} {digits[SAS_DIGITS // 2:]}"


def finish_message(nonce: str, accept: bool) -> bytes:
    return FINISH_PREFIX + nonce.encode() + b"\x00" + (b"accept" if accept else b"cancel")


def verify_finish(public_key: str, nonce: str, accept: bool, signature: object) -> bool:
    raw = unb64url(signature, 64)
    if raw is None:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(decode_public_key(public_key)).verify(raw, finish_message(nonce, accept))
    except (InvalidSignature, ValueError, GrantError):
        return False
    return True


@dataclass
class Pending:

    nonce: str
    proof: str
    sas: str
    label: str
    fid: str
    expires: float
    data: Dict[str, Any] = field(default_factory=dict)


class PendingPairs:

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._items: Dict[str, Pending] = {}

    def _sweep(self) -> None:
        now = self._clock()
        for nonce in [n for n, p in self._items.items() if p.expires <= now]:
            del self._items[nonce]

    def add(self, nonce: str, *, proof: str, sas: str, label: str, fid: str, **data: Any) -> Pending:
        self._sweep()
        if len(self._items) >= MAX_PENDING:
            del self._items[next(iter(self._items))]
        pending = self._items[nonce] = Pending(nonce, proof, sas, label, fid,
                                               self._clock() + PENDING_TTL_SECONDS, dict(data))
        return pending

    def get(self, nonce: object) -> Optional[Pending]:
        self._sweep()
        return self._items.get(nonce) if isinstance(nonce, str) else None

    def pop(self, nonce: object) -> Optional[Pending]:
        self._sweep()
        return self._items.pop(nonce, None) if isinstance(nonce, str) else None

    def all(self) -> List[Pending]:
        self._sweep()
        return list(self._items.values())

    def seconds_left(self, pending: Pending) -> int:
        return max(0, int(pending.expires - self._clock()))


ACCEPTING = PendingPairs()
INITIATING = PendingPairs()
