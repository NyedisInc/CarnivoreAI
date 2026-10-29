
from __future__ import annotations

import base64
import binascii
import hmac
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import BinaryIO, Callable, List, Optional, Sequence, Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from src.core.crate_crypto.errors import HeaderMacMismatch, KeyFormatError, Malformed, WrongKey

INTRO: bytes = b"age-encryption.org/v1\n"
STANZA_PREFIX: bytes = b"-> "
MAC_PREFIX: bytes = b"---"
X25519_TYPE: bytes = b"X25519"
X25519_INFO: bytes = b"age-encryption.org/v1/X25519"
HEADER_INFO: bytes = b"header"
FILE_KEY_BYTES: int = 16
WRAPPED_KEY_BYTES: int = FILE_KEY_BYTES + 16
SHARE_BYTES: int = 32
MAC_BYTES: int = 32
COLUMNS: int = 64
MAX_HEADER_BYTES: int = 64 * 1024
MAX_STANZAS: int = 20
_ZERO_NONCE: bytes = bytes(12)
_B64_TEXT = re.compile(rb"[A-Za-z0-9+/]*")


@dataclass(frozen=True)
class Stanza:

    args: Tuple[bytes, ...]
    body: bytes


@dataclass(frozen=True)
class Header:

    stanzas: Tuple[Stanza, ...]
    mac: bytes
    mac_input: bytes
    length: int


def b64encode(data: bytes) -> bytes:
    return base64.b64encode(data).rstrip(b"=")


def b64decode(text: bytes) -> bytes:
    if not _B64_TEXT.fullmatch(text) or len(text) % 4 == 1:
        raise Malformed("header base64 is not valid")
    try:
        data = base64.b64decode(text + b"=" * (-len(text) % 4), validate=True)
    except binascii.Error:
        raise Malformed("header base64 is not valid") from None
    if b64encode(data) != text:
        raise Malformed("header base64 is not canonical")
    return data


def hkdf(ikm: bytes, salt: bytes, info: bytes, length: int = 32) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt or None, info=info).derive(ikm)


def header_mac(file_key: bytes, mac_input: bytes) -> bytes:
    return hmac.new(hkdf(file_key, b"", HEADER_INFO), mac_input, sha256).digest()


def _arg_ok(arg: bytes) -> bool:
    return bool(arg) and all(0x21 <= c <= 0x7E for c in arg)


def _check_x25519(args: Tuple[bytes, ...], body: bytes) -> None:
    if len(args) != 2:
        raise Malformed("an X25519 stanza takes exactly one argument")
    if len(b64decode(args[1])) != SHARE_BYTES:
        raise Malformed("an X25519 share must be 32 bytes")
    if len(body) != WRAPPED_KEY_BYTES:
        raise Malformed("an X25519 stanza body must be 32 bytes")


def _line(buf: bytes, pos: int) -> Tuple[bytes, int]:
    end = buf.find(b"\n", pos)
    if end < 0:
        raise Malformed("age header is truncated or longer than 64 KiB")
    return buf[pos:end], end + 1


def parse_header(buf: bytes) -> Header:
    buf = buf[:MAX_HEADER_BYTES]
    if not buf.startswith(INTRO):
        raise Malformed("not an age v1 file")
    pos, stanzas = len(INTRO), []
    while True:
        line, nxt = _line(buf, pos)
        if line.startswith(MAC_PREFIX):
            if not line.startswith(MAC_PREFIX + b" "):
                raise Malformed("the header MAC line is malformed")
            mac = b64decode(line[len(MAC_PREFIX) + 1:])
            if len(mac) != MAC_BYTES:
                raise Malformed("the header MAC must be 32 bytes")
            return Header(tuple(stanzas), mac, buf[:pos + len(MAC_PREFIX)], nxt)
        if not line.startswith(STANZA_PREFIX):
            raise Malformed("a header line is neither a stanza nor the MAC")
        args = tuple(line[len(STANZA_PREFIX):].split(b" "))
        if not all(_arg_ok(a) for a in args):
            raise Malformed("a stanza argument is empty or has a character outside printable ASCII")
        body_text, pos = b"", nxt
        while True:
            body_line, pos = _line(buf, pos)
            if len(body_line) > COLUMNS:
                raise Malformed("a stanza body line is longer than 64 columns")
            body_text += body_line
            if len(body_line) < COLUMNS:
                break
        body = b64decode(body_text)
        if args[0] == X25519_TYPE:
            _check_x25519(args, body)
        stanzas.append(Stanza(args, body))
        if len(stanzas) > MAX_STANZAS:
            raise Malformed(f"an age header with more than {MAX_STANZAS} stanzas is refused")


def header_ok(raw: BinaryIO) -> bool:
    try:
        parse_header(raw.read(MAX_HEADER_BYTES))
    except Malformed:
        return False
    return True


def _public(secret: X25519PrivateKey) -> bytes:
    return secret.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _shared(secret: X25519PrivateKey, peer: bytes) -> bytes:
    try:
        shared = secret.exchange(X25519PublicKey.from_public_bytes(peer))
    except ValueError:
        raise Malformed("an X25519 share gives the all-zero shared secret") from None
    if not any(shared):
        raise Malformed("an X25519 share gives the all-zero shared secret")
    return shared


def _unwrap(stanza: Stanza, identity: bytes) -> Optional[bytes]:
    share = b64decode(stanza.args[1])
    secret = X25519PrivateKey.from_private_bytes(identity)
    shared = _shared(secret, share)
    key = hkdf(shared, share + _public(secret), X25519_INFO)
    try:
        return ChaCha20Poly1305(key).decrypt(_ZERO_NONCE, stanza.body, None)
    except InvalidTag:
        return None


def open_file_key(header: Header, identities: Sequence[bytes]) -> bytes:
    for stanza in header.stanzas:
        if stanza.args[0] != X25519_TYPE:
            continue
        for identity in identities:
            file_key = _unwrap(stanza, identity)
            if file_key is not None:
                if not hmac.compare_digest(header_mac(file_key, header.mac_input), header.mac):
                    raise HeaderMacMismatch("the age header MAC does not match; the header was changed")
                return file_key
    raise WrongKey("no recipient stanza opens with the given identity")


def _wrap_lines(body: bytes) -> bytes:
    text = b64encode(body)
    lines = [text[i:i + COLUMNS] for i in range(0, len(text), COLUMNS)]
    if not lines or len(lines[-1]) == COLUMNS:
        lines.append(b"")
    return b"".join(line + b"\n" for line in lines)


def build_header(recipients: Sequence[bytes], file_key: bytes, rng: Callable[[int], bytes]) -> bytes:
    if not 1 <= len(recipients) <= MAX_STANZAS:
        raise KeyFormatError(f"an age file needs 1 to {MAX_STANZAS} recipients")
    parts: List[bytes] = [INTRO]
    for recipient in recipients:
        ephemeral = X25519PrivateKey.from_private_bytes(rng(32))
        share = _public(ephemeral)
        try:
            shared = _shared(ephemeral, recipient)
        except Malformed:
            raise KeyFormatError("a recipient key is not a usable X25519 point") from None
        wrapped = ChaCha20Poly1305(hkdf(shared, share + recipient, X25519_INFO)).encrypt(_ZERO_NONCE, file_key, None)
        parts.append(STANZA_PREFIX + X25519_TYPE + b" " + b64encode(share) + b"\n" + _wrap_lines(wrapped))
    mac_input = b"".join(parts) + MAC_PREFIX
    return mac_input + b" " + b64encode(header_mac(file_key, mac_input)) + b"\n"
