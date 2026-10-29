"""Verifying a minisign signature in process, over ``cryptography``'s Ed25519.

WHY NOT SHELL OUT TO ``minisign``. The binary is not installed on a user's
Mac, it is not something an Electron bundle may assume, and a verifier that
silently does not run is the false-green shape this project has spent months
removing. The format is 42 bytes of public key and 74 bytes of signature, so
the whole of it is parsed here and the only cryptography is one Ed25519
verify per signature.

THE TWO ALGORITHMS, AND WHY THE CALLER MUST NAME THE ONE IT EXPECTS.

- ``ED`` is PREHASHED: the Ed25519 signature covers BLAKE2b-512 of the
  message, not the message. This is what ``minisign -S`` writes by default
  (measured against minisign 0.12), and it is the one the catalog index is
  signed with.
- ``Ed`` is the LEGACY format (``minisign -S -l``): the signature covers the
  raw message. It is accepted so that a legacy vector parses and verifies
  rather than failing as "malformed", but the catalog never emits it.

Anything else is :class:`MinisignFormatError`. An unknown algorithm is a
refusal, never a fall-through to "assume raw".

THE 2 BYTE ALGORITHM MARKER SITS OUTSIDE BOTH SIGNATURES, SO IT IS INPUT
AND NEVER EVIDENCE. The mathematics covers the 64 signature bytes and the
trusted comment; the marker in front of them is covered by nothing, so
whoever hands this verifier a signature chooses it. Flipping a real
``ED`` signature to ``Ed`` leaves every signature byte untouched and only
changes which payload this module checks them against, so a verifier that
read the marker as fact would answer True over the 64 digest bytes the
publisher never signed. A valid signature over a DIFFERENT statement is
exactly the shape an index body or a release statement could be swapped
for.

BOTH SIGNATURES ARE ALWAYS CHECKED. A minisign file carries two: the one
over the message, and a GLOBAL signature over ``sig || trusted_comment``.
The trusted comment is the only part of the file a verifier is entitled to
believe, and it is only trustworthy because of that second signature, so
:func:`verify` checks it every time rather than offering a mode that skips
it. A vector whose ONLY mutation is the trusted comment must fail, and the
test suite proves it does.

NOTHING HERE LOGS KEY MATERIAL OR A SIGNATURE. Key IDs are logged, because
a key id is a public identifier minisign itself prints and a mismatch is
undebuggable without it. Raw keys, signatures and base64 payloads never
reach a log line, an exception message or a repr.
"""

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
    """A key or signature could not be parsed as minisign.

    This is the MALFORMED outcome and it is deliberately distinct from a
    cryptographic failure. :func:`verify` returns False when the bytes
    parsed and the mathematics disagreed; it raises this when there were
    never well-formed bytes to check. Collapsing the two would let "we
    could not look" read as "we looked and it was wrong".
    """


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
