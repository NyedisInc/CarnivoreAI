
from __future__ import annotations

import secrets
import struct
import time
from typing import Dict, Optional, Tuple

import jwt
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from src.core.federation.grants import Grant, GrantError, decode_public_key
from src.core.relay_identity.device_key import unb64url

PEER_TYP = "peer"
TOKEN_TTL_SECONDS = 15 * 60
CHALLENGE_FRESHNESS_SECONDS = 60
CHALLENGE_PREFIX = b"carnivore federation v1 token\x00"

_SIGNING_KEY = secrets.token_bytes(32)


class PeerTokenError(Exception):
    pass


def challenge_message(grant_id: str, issuer_install_id: str, ts: int, nonce: bytes) -> bytes:
    return (CHALLENGE_PREFIX + grant_id.encode() + b"\x00" + issuer_install_id.encode()
            + b"\x00" + struct.pack(">q", ts) + nonce)


class NonceCache:

    def __init__(self) -> None:
        self._seen: Dict[Tuple[str, str], float] = {}

    def accept(self, grant_id: str, nonce: str, now: float) -> bool:
        horizon = now - 2 * CHALLENGE_FRESHNESS_SECONDS
        for key in [k for k, at in self._seen.items() if at < horizon]:
            del self._seen[key]
        if (grant_id, nonce) in self._seen:
            return False
        self._seen[(grant_id, nonce)] = now
        return True


NONCES = NonceCache()


def verify_challenge(grant: Grant, issuer_install_id: str, ts: object, nonce: object,
                     signature: object, *, now: Optional[float] = None,
                     nonces: NonceCache = NONCES) -> None:
    now = time.time() if now is None else now
    if not isinstance(ts, int) or isinstance(ts, bool) or abs(now - ts) > CHALLENGE_FRESHNESS_SECONDS:
        raise PeerTokenError("challenge stale")
    raw_nonce, raw_sig = unb64url(nonce, 16), unb64url(signature, 64)
    if raw_nonce is None or raw_sig is None:
        raise PeerTokenError("challenge malformed")
    try:
        Ed25519PublicKey.from_public_bytes(decode_public_key(grant.public_key)).verify(
            raw_sig, challenge_message(grant.grant_id, issuer_install_id, ts, raw_nonce))
    except (InvalidSignature, ValueError, GrantError) as exc:
        raise PeerTokenError("challenge refused") from exc
    if not nonces.accept(grant.grant_id, str(nonce), now):
        raise PeerTokenError("challenge replayed")


def mint(grant: Grant, issuer_install_id: str, *, now: Optional[float] = None) -> Tuple[str, int]:
    issued = int(time.time() if now is None else now)
    claims = {"typ": PEER_TYP, "sub": grant.grant_id, "iid": issuer_install_id,
              "iat": issued, "exp": issued + TOKEN_TTL_SECONDS, "jti": secrets.token_hex(8)}
    return jwt.encode(claims, _SIGNING_KEY, algorithm="HS256"), TOKEN_TTL_SECONDS


def is_peer_token(token: str) -> bool:
    try:
        return jwt.decode(token, options={"verify_signature": False}).get("typ") == PEER_TYP
    except jwt.InvalidTokenError:
        return False


def decode(token: str, issuer_install_id: str) -> Dict[str, object]:
    try:
        claims = jwt.decode(token, _SIGNING_KEY, algorithms=["HS256"])
    except jwt.InvalidTokenError as exc:
        raise PeerTokenError("token refused") from exc
    if claims.get("typ") != PEER_TYP or claims.get("iid") != issuer_install_id or not claims.get("sub"):
        raise PeerTokenError("token refused")
    return claims
