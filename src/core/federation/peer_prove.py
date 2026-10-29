
from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from src.core.federation.grants import GrantError, decode_public_key
from src.core.relay_identity.device_key import unb64url

PROVE_PREFIX = b"carnivore federation v1 prove\x00"

LIVE_ROUTES: "set[str]" = set()


def prove_message(nonce: bytes, install_id: str, route: str = "") -> bytes:
    return PROVE_PREFIX + nonce + b"\x00" + install_id.encode() + (b"\x00" + route.encode() if route else b"")


def verify(public_key_b64: str, nonce: bytes, install_id: str, signature: object, route: str = "") -> bool:
    raw = unb64url(signature, 64)
    if raw is None:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(decode_public_key(public_key_b64)).verify(
            raw, prove_message(nonce, install_id, route))
    except (InvalidSignature, ValueError, GrantError):
        return False
    return True
