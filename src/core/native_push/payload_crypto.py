
from __future__ import annotations

import os
from typing import Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION = 1
NONCE_BYTES = 12
TAG_BYTES = 16
KEY_BYTES = 32
AAD_PREFIX = b"carnivore-apns-v1\x00"
MAX_PLAINTEXT_BYTES = 1800 - 1 - NONCE_BYTES - TAG_BYTES


def associated_data(device_row_id: str) -> bytes:
    return AAD_PREFIX + device_row_id.encode("utf-8")


def seal(key: bytes, device_row_id: str, plaintext: bytes, *, nonce: Optional[bytes] = None) -> bytes:
    if len(key) != KEY_BYTES:
        raise ValueError("the payload key must be 32 bytes")
    if len(plaintext) > MAX_PLAINTEXT_BYTES:
        raise ValueError("the payload is too large")
    nonce = os.urandom(NONCE_BYTES) if nonce is None else nonce
    if len(nonce) != NONCE_BYTES:
        raise ValueError("the nonce must be 12 bytes")
    return bytes([VERSION]) + nonce + AESGCM(key).encrypt(nonce, plaintext, associated_data(device_row_id))


def open_blob(key: bytes, device_row_id: str, blob: bytes) -> bytes:
    if len(key) != KEY_BYTES or len(blob) < 1 + NONCE_BYTES + TAG_BYTES or blob[0] != VERSION:
        raise ValueError("not a version 1 blob")
    try:
        return AESGCM(key).decrypt(blob[1:1 + NONCE_BYTES], blob[1 + NONCE_BYTES:], associated_data(device_row_id))
    except InvalidTag as exc:
        raise ValueError("the blob does not authenticate") from exc
