
from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
import secrets
import struct
from dataclasses import dataclass, field
from typing import Callable, Optional, Tuple

import structlog
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from src.core import relay_keychain

logger = structlog.get_logger()

AUDIENCE = b"relay.carnivore.ai"
REGISTER_PREFIX = b"carnivore relay v2 register\x00"
TOKEN_PREFIX = b"carnivore relay v2 token\x00"
CLAIM_PREFIX = b"carnivore relay v2 claim\x00"
POP_PREFIX = b"carnivore relay v2 pop\x00"
POP_AUDIENCE = b"relay.carnivore.ai/publish"
LINK_ID_PREFIX = b"carnivore relay v2 link-id"
LINK_TUNNEL_POP_AUDIENCE = b"relay.carnivore.ai/link-tunnel"
ACME_TXT_PREFIX = b"carnivore-relay-acme-txt-v1\x00"
CUSTOM_DOMAIN_PREFIX = b"carnivore-relay-custom-domain-v1\x00"
APNS_PREFIX = b"carnivore-relay-apns-v1\x00"
ACME_ACTIONS = ("set", "clear", "status")

_B64URL_RE = re.compile(r"\A[A-Za-z0-9_-]*\Z")


class DeviceKeyUnavailable(RuntimeError):
    """The device key could not be read or stored. Never carries the seed."""


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def unb64url(text: object, length: Optional[int] = None) -> Optional[bytes]:
    if not isinstance(text, str) or not _B64URL_RE.match(text):
        return None
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError):
        return None
    if b64url(raw) != text or (length is not None and len(raw) != length):
        return None
    return raw


def device_id_for(raw_pub: bytes) -> str:
    digest = hashlib.sha256(raw_pub).digest()[:16]
    return base64.b32encode(digest).decode("ascii").rstrip("=").lower()


def _be8(ts: int) -> bytes:
    return struct.pack(">q", ts)


def register_message(device_id: str, raw_pub: bytes, ts: int) -> bytes:
    return REGISTER_PREFIX + device_id.encode("ascii") + b"\x00" + raw_pub + _be8(ts)


def token_message(device_id: str, ts: int, nonce: bytes) -> bytes:
    dev = device_id.encode("ascii")
    return TOKEN_PREFIX + dev + b"\x00" + dev + b"\x00" + _be8(ts) + nonce + AUDIENCE


def claim_message(device_id: str, account: str, ts: int, nonce: bytes) -> bytes:
    return (CLAIM_PREFIX + device_id.encode("ascii") + b"\x00" + account.encode("ascii")
            + b"\x00" + _be8(ts) + nonce + AUDIENCE)


def pop_message(jti: str, ts: int) -> bytes:
    return POP_PREFIX + jti.encode("ascii") + b"\x00" + _be8(ts) + POP_AUDIENCE


def link_tunnel_pop_message(jti: str, ts: int) -> bytes:
    return POP_PREFIX + jti.encode("ascii") + b"\x00" + _be8(ts) + LINK_TUNNEL_POP_AUDIENCE


def acme_txt_message(device_id: str, ts: int, nonce: bytes, action: str, arg: str) -> bytes:
    return (ACME_TXT_PREFIX + device_id.encode("ascii") + b"\x00" + _be8(ts) + nonce
            + action.encode("ascii") + b"\x00" + arg.encode("ascii") + b"\x00" + AUDIENCE)


def custom_domain_message(device_id: str, ts: int, nonce: bytes, action: str, domain: str, acct_uri: str) -> bytes:
    return (CUSTOM_DOMAIN_PREFIX + device_id.encode("ascii") + b"\x00" + _be8(ts) + nonce
            + action.encode("ascii") + b"\x00" + domain.encode("ascii") + b"\x00"
            + acct_uri.encode("ascii") + b"\x00" + AUDIENCE)


def apns_message(device_id: str, ts: int, nonce: bytes, environment: str, token: str,
                 collapse_id: str, ciphertext: bytes) -> bytes:
    return (APNS_PREFIX + device_id.encode("ascii") + b"\x00" + _be8(ts) + nonce
            + environment.encode("ascii") + b"\x00" + token.encode("ascii") + b"\x00"
            + collapse_id.encode("ascii") + b"\x00" + hashlib.sha256(ciphertext).digest() + AUDIENCE)


def link_id_for(device_id: str, nonce: bytes) -> str:
    digest = hashlib.sha256(LINK_ID_PREFIX + device_id.encode("ascii") + nonce).digest()
    return b64url(digest[:16])


@dataclass(frozen=True)
class DeviceKey:

    raw_pub: bytes
    device_id: str
    _private: Ed25519PrivateKey = field(repr=False, compare=False)
    _seed: bytes = field(default=b"", repr=False, compare=False)

    @classmethod
    def from_seed(cls, seed: bytes) -> "DeviceKey":
        private = Ed25519PrivateKey.from_private_bytes(seed)
        raw_pub = private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return cls(raw_pub=raw_pub, device_id=device_id_for(raw_pub), _private=private, _seed=seed)

    def sign(self, message: bytes) -> str:
        return b64url(self._private.sign(message))

    def derive_seed(self, info: bytes, salt: bytes) -> bytes:
        if len(self._seed) != 32:
            raise DeviceKeyUnavailable("this key cannot derive a seed")
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(self._seed)


ReadState = Callable[[str, str], Tuple[str, Optional[str]]]
Write = Callable[..., None]


def load_or_create(
    install_id: str,
    *,
    read: ReadState = relay_keychain.read_password_state,
    write: Write = relay_keychain.write_password,
    service: str = relay_keychain.DEVICE_KEY_SERVICE,
) -> DeviceKey:
    """This install's device key, minting and storing one only when absent.

    Description: blocking (it runs ``security``); call it off the loop.
      The mint is CREATE-ONLY (never ``-U``) and the item is then read
      back, so of two processes racing to mint, the second write fails and
      both use the one key that landed first.
    Inputs: install_id (str) - the Keychain account; read and write - the
      Keychain seam, injected by tests so the real Keychain is never used;
      service (str) - the item, the relay's by default (the federation key
      passes its own, ``src/core/federation/fed_key.py``).
    Output: DeviceKey.
    Raises: DeviceKeyUnavailable - the Keychain could not be read or
      written, or holds something that is not a seed.
    Example: key = load_or_create(install_id)
    """
    state, value = read(service, install_id)
    if state == relay_keychain.READ_ABSENT:
        try:
            write(service, install_id, b64url(secrets.token_bytes(32)), replace=False)
            logger.info("relay_device_key_created")
        except relay_keychain.KeychainWriteError as exc:
            logger.info("relay_device_key_create_refused", error=str(exc))
        state, value = read(service, install_id)
    if state != relay_keychain.READ_OK:
        raise DeviceKeyUnavailable("the login keychain did not answer")
    seed = unb64url(value, 32)
    if seed is None:
        raise DeviceKeyUnavailable("the stored device key is malformed")
    return DeviceKey.from_seed(seed)


def load_or_create_file(install_id: str, path: str) -> DeviceKey:
    """The device key from a 0600 file, minting it only when the file is absent.

    Description: the file-backed identity for a test slot, whose private HOME
      has no login Keychain (``relay.device_key_file``). Same rules as
      :func:`load_or_create`: create-only (``O_EXCL``, so a race leaves one
      key), a file that cannot be read or is malformed is
      :class:`DeviceKeyUnavailable` and is never replaced. Blocking.
    Inputs: install_id (str) - unused, kept so this fits ``key_loader``;
      path (str) - the key file, in an already private directory.
    Output: DeviceKey.
    Raises: DeviceKeyUnavailable.
    Example: key = load_or_create_file(install_id, "/slot/state/relay-device.key")
    """
    del install_id
    target = os.path.expanduser(path)
    if not os.path.isabs(target):
        raise DeviceKeyUnavailable("the device key file path must be absolute")
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    except OSError as exc:
        raise DeviceKeyUnavailable("the device key file could not be created") from exc
    else:
        with os.fdopen(fd, "w") as handle:
            handle.write(b64url(secrets.token_bytes(32)))
        logger.info("relay_device_key_created", store="file")
    try:
        with open(target, "r", encoding="ascii") as handle:
            info = os.fstat(handle.fileno())
            if info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise DeviceKeyUnavailable("the device key file is not private to this user")
            value = handle.read().strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise DeviceKeyUnavailable("the device key file could not be read") from exc
    seed = unb64url(value, 32)
    if seed is None:
        raise DeviceKeyUnavailable("the stored device key is malformed")
    return DeviceKey.from_seed(seed)


TEST_SLOT_ENV = relay_keychain.TEST_SLOT_ENV


def key_loader_for(key_file: str) -> Callable[[str], DeviceKey]:
    if not key_file:
        return load_or_create
    if not os.environ.get(TEST_SLOT_ENV):
        logger.warning("relay_device_key_file_ignored", why="not a test slot")
        return load_or_create
    return lambda install_id: load_or_create_file(install_id, key_file)
