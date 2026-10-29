
from __future__ import annotations

from typing import Tuple

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from src.core.crate_crypto import bech32
from src.core.crate_crypto.errors import KeyFormatError

RECIPIENT_HRP: str = "age"
IDENTITY_HRP: str = "age-secret-key-"
KEY_BYTES: int = 32


def _decode_key(text: str, hrp: str, upper: bool, what: str) -> bytes:
    if text != (text.upper() if upper else text.lower()):
        raise KeyFormatError(f"an age {what} must be all {'upper' if upper else 'lower'} case")
    try:
        found_hrp, data = bech32.decode(text)
    except ValueError as exc:
        raise KeyFormatError(f"not a valid age {what}: {exc}") from None
    if found_hrp != hrp:
        raise KeyFormatError(f"not an age {what} (wrong prefix)")
    if len(data) != KEY_BYTES:
        raise KeyFormatError(f"an age {what} holds {KEY_BYTES} bytes, this one holds {len(data)}")
    return data


def parse_recipient(text: str) -> bytes:
    return _decode_key(text.strip(), RECIPIENT_HRP, False, "recipient")


def parse_identity(text: str) -> bytes:
    lines = [line.strip() for line in text.splitlines()]
    keys = [line for line in lines if line and not line.startswith("#")]
    if len(keys) != 1:
        raise KeyFormatError(f"expected one age identity line, found {len(keys)}")
    return _decode_key(keys[0], IDENTITY_HRP, True, "identity")


def _public_of(secret: bytes) -> bytes:
    return X25519PrivateKey.from_private_bytes(secret).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def encode_recipient(public: bytes) -> str:
    if len(public) != KEY_BYTES:
        raise KeyFormatError(f"an X25519 public key is {KEY_BYTES} bytes")
    return bech32.encode(RECIPIENT_HRP, public)


def encode_identity(secret: bytes) -> str:
    if len(secret) != KEY_BYTES:
        raise KeyFormatError(f"an X25519 private key is {KEY_BYTES} bytes")
    return bech32.encode(IDENTITY_HRP, secret).upper()


def generate() -> Tuple[str, str]:
    secret = X25519PrivateKey.generate().private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return encode_identity(secret), encode_recipient(_public_of(secret))


def recipient_of(identity: str) -> str:
    return encode_recipient(_public_of(parse_identity(identity)))
