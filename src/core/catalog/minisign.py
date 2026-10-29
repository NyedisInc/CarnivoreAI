
from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass

import structlog
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

logger = structlog.get_logger(__name__)

ALG_PREHASHED: bytes = b"ED"

ALG_LEGACY: bytes = b"Ed"

_PUBLIC_KEY_ALG: bytes = b"Ed"

_KEY_ID_BYTES: int = 8
_ED25519_PUBLIC_KEY_BYTES: int = 32
_ED25519_SIGNATURE_BYTES: int = 64

_PUBLIC_KEY_BLOB_BYTES: int = 42

_SIGNATURE_BLOB_BYTES: int = 74

_UNTRUSTED_COMMENT_PREFIX: str = "untrusted comment: "
_TRUSTED_COMMENT_PREFIX: str = "trusted comment: "


class MinisignFormatError(ValueError):
    pass


def format_key_id(raw: bytes) -> str:
    if len(raw) != _KEY_ID_BYTES:
        raise MinisignFormatError(
            f"key id must be {_KEY_ID_BYTES} bytes, got {len(raw)}"
        )
    return "%016X" % int.from_bytes(raw, "little")


def _decode_base64(text: str, *, what: str) -> bytes:
    try:
        return base64.b64decode(text.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MinisignFormatError(f"{what} is not valid base64") from exc


@dataclass(frozen=True)
class PublicKey:

    key_id: str
    raw: bytes


@dataclass(frozen=True)
class Signature:

    key_id: str
    sig: bytes
    trusted_comment: str
    global_sig: bytes
    prehashed: bool

    @classmethod
    def from_index_fields(
        cls,
        key_id: str,
        sig_b64: str,
        trusted_comment: str,
        global_sig_b64: str,
    ) -> "Signature":
        signature = _signature_from_blobs(
            _decode_base64(sig_b64, what="signature"),
            trusted_comment,
            _decode_base64(global_sig_b64, what="global signature"),
        )
        wanted = key_id.strip().upper()
        if wanted != signature.key_id:
            raise MinisignFormatError(
                "index sig block key id does not match the signature it "
                f"carries: {wanted} vs {signature.key_id}"
            )
        return signature


def _signature_from_blobs(
    blob: bytes, trusted_comment: str, global_sig: bytes,
) -> Signature:
    if len(blob) != _SIGNATURE_BLOB_BYTES:
        raise MinisignFormatError(
            f"signature must be {_SIGNATURE_BLOB_BYTES} bytes, "
            f"got {len(blob)}"
        )
    if len(global_sig) != _ED25519_SIGNATURE_BYTES:
        raise MinisignFormatError(
            f"global signature must be {_ED25519_SIGNATURE_BYTES} bytes, "
            f"got {len(global_sig)}"
        )
    alg = blob[:2]
    if alg == ALG_PREHASHED:
        prehashed = True
    elif alg == ALG_LEGACY:
        prehashed = False
    else:
        raise MinisignFormatError(
            f"unknown signature algorithm: {alg!r}"
        )
    return Signature(
        key_id=format_key_id(blob[2:10]),
        sig=blob[10:],
        trusted_comment=trusted_comment,
        global_sig=global_sig,
        prehashed=prehashed,
    )


def _base64_line(text: str, *, what: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise MinisignFormatError(f"{what} is empty")
    if lines[0].startswith(_UNTRUSTED_COMMENT_PREFIX):
        lines = lines[1:]
    if not lines:
        raise MinisignFormatError(f"{what} carries a comment and no key line")
    return lines[0]


def parse_public_key(text: str) -> PublicKey:
    blob = _decode_base64(
        _base64_line(text, what="public key"), what="public key"
    )
    if len(blob) != _PUBLIC_KEY_BLOB_BYTES:
        raise MinisignFormatError(
            f"public key must be {_PUBLIC_KEY_BLOB_BYTES} bytes, "
            f"got {len(blob)}"
        )
    if blob[:2] != _PUBLIC_KEY_ALG:
        raise MinisignFormatError(
            f"unknown public key algorithm: {blob[:2]!r}"
        )
    return PublicKey(key_id=format_key_id(blob[2:10]), raw=blob[10:])


def parse_signature(text: str) -> Signature:
    lines = text.splitlines()
    if len(lines) < 4:
        raise MinisignFormatError(
            f"signature file must have 4 lines, got {len(lines)}"
        )
    if not lines[2].startswith(_TRUSTED_COMMENT_PREFIX):
        raise MinisignFormatError(
            "signature file line 3 is not a trusted comment"
        )
    return _signature_from_blobs(
        _decode_base64(lines[1], what="signature"),
        lines[2][len(_TRUSTED_COMMENT_PREFIX):],
        _decode_base64(lines[3], what="global signature"),
    )


def _ed25519_ok(
    public_key: PublicKey, signature: bytes, payload: bytes,
) -> bool:
    if len(public_key.raw) != _ED25519_PUBLIC_KEY_BYTES:
        raise MinisignFormatError(
            f"public key must be {_ED25519_PUBLIC_KEY_BYTES} bytes, "
            f"got {len(public_key.raw)}"
        )
    if len(signature) != _ED25519_SIGNATURE_BYTES:
        raise MinisignFormatError(
            f"signature must be {_ED25519_SIGNATURE_BYTES} bytes, "
            f"got {len(signature)}"
        )
    try:
        Ed25519PublicKey.from_public_bytes(public_key.raw).verify(
            signature, payload
        )
    except InvalidSignature:
        return False
    return True


def _algorithm_name(prehashed: bool) -> str:
    return (ALG_PREHASHED if prehashed else ALG_LEGACY).decode("ascii")


def verify(
    message: bytes,
    signature: Signature,
    public_key: PublicKey,
    *,
    expect_prehashed: bool,
) -> bool:
    if signature.prehashed != expect_prehashed:
        logger.warning(
            "minisign_algorithm_mismatch",
            expected_algorithm=_algorithm_name(expect_prehashed),
            actual_algorithm=_algorithm_name(signature.prehashed),
        )
        return False

    if signature.key_id != public_key.key_id:
        logger.warning(
            "catalog_minisign_key_id_mismatch",
            signature_key_id=signature.key_id,
            public_key_id=public_key.key_id,
        )
        return False

    payload = (
        hashlib.blake2b(message, digest_size=64).digest()
        if expect_prehashed
        else message
    )
    if not _ed25519_ok(public_key, signature.sig, payload):
        logger.warning(
            "catalog_minisign_message_signature_invalid",
            key_id=public_key.key_id,
            prehashed=signature.prehashed,
            message_bytes=len(message),
        )
        return False

    global_payload = signature.sig + signature.trusted_comment.encode("utf-8")
    if not _ed25519_ok(public_key, signature.global_sig, global_payload):
        logger.warning(
            "catalog_minisign_global_signature_invalid",
            key_id=public_key.key_id,
        )
        return False

    return True
