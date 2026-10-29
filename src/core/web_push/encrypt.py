
from __future__ import annotations

import os
import struct
from typing import Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

RECORD_SIZE = 4096
MAX_PLAINTEXT = RECORD_SIZE - 17


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt_payload(plaintext: bytes, ua_public: bytes, auth_secret: bytes, *, salt: Optional[bytes] = None,
                    as_private: Optional[ec.EllipticCurvePrivateKey] = None) -> bytes:
    if len(plaintext) > MAX_PLAINTEXT:
        raise ValueError("payload too large for one record")
    if len(auth_secret) != 16:
        raise ValueError("auth secret must be 16 bytes")
    salt = os.urandom(16) if salt is None else salt
    as_private = as_private or ec.generate_private_key(ec.SECP256R1())
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    as_public = as_private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    shared = as_private.exchange(ec.ECDH(), ua_key)
    ikm = _hkdf(auth_secret, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    sealed = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)
    return salt + struct.pack(">IB", RECORD_SIZE, len(as_public)) + as_public + sealed
