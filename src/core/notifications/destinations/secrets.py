
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
from typing import Callable, Mapping, Optional, Protocol

import structlog

from src.core import relay_keychain

log = structlog.get_logger(__name__)

SERVICE = relay_keychain.NOTIFICATIONS_SERVICE

_DEST_ID = re.compile(r"d_[0-9a-f]{12}")

_FIELD_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}")

MAX_ENCODED_BYTES = 4096

_VERSION = 1


class SecretError(Exception):
    pass


class InvalidDestinationId(SecretError):
    pass


class InvalidFields(SecretError):
    pass


class SecretTooLarge(SecretError):
    """The encoded value exceeds MAX_ENCODED_BYTES."""


class CorruptSecret(SecretError):
    pass


class SecretStoreUnavailable(SecretError):
    """The Keychain could not be read (locked, timed out, refused) or written."""


class KeychainBackend(Protocol):

    def read_state(self, service: str, account: str) -> tuple[str, Optional[str]]: ...

    def write(self, service: str, account: str, secret: str) -> None: ...

    def delete(self, service: str, account: str) -> bool: ...


class _SecurityBackend:

    def read_state(self, service: str, account: str) -> tuple[str, Optional[str]]:
        return relay_keychain.read_password_state(service, account)

    def write(self, service: str, account: str, secret: str) -> None:
        relay_keychain.write_password(service, account, secret)

    def delete(self, service: str, account: str) -> bool:
        return relay_keychain.delete_password(service, account)


def check_dest_id(dest_id: str) -> str:
    if not isinstance(dest_id, str) or not _DEST_ID.fullmatch(dest_id):
        raise InvalidDestinationId("destination id must be d_ plus 12 lowercase hex characters")
    return dest_id


def encode(fields: Mapping[str, str]) -> str:
    for name, value in fields.items():
        if not isinstance(name, str) or not _FIELD_NAME.fullmatch(name):
            raise InvalidFields("field names are short lowercase identifiers")
        if not isinstance(value, str):
            raise InvalidFields(f"field {name} must be a string")
    raw = json.dumps({"v": _VERSION, "fields": dict(fields)}, separators=(",", ":"), ensure_ascii=False)
    encoded = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")
    if len(encoded) > MAX_ENCODED_BYTES:
        raise SecretTooLarge(f"encoded secret exceeds {MAX_ENCODED_BYTES} bytes")
    return encoded


def decode(encoded: str) -> dict[str, str]:
    try:
        data = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8"))
    except (binascii.Error, UnicodeError, ValueError):
        raise CorruptSecret("the stored secret is not decodable") from None
    fields = data.get("fields") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("v") != _VERSION or not isinstance(fields, dict):
        raise CorruptSecret("the stored secret has an unknown shape")
    for name, value in fields.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise CorruptSecret("the stored secret has a non-string field")
    return dict(fields)


def merge(old: Optional[Mapping[str, str]], patch: Mapping[str, Optional[str]]) -> dict[str, str]:
    merged = dict(old or {})
    for name, value in patch.items():
        if isinstance(value, str) and value.strip() != "":
            merged[name] = value
    return merged


class DestinationSecrets:

    def __init__(self, *, backend: Optional[KeychainBackend] = None, service: str = SERVICE,
                 check_id: Callable[[str], str] = check_dest_id, event: str = "notif_secret") -> None:
        self._backend: KeychainBackend = backend or _SecurityBackend()
        self._service = service
        self._check = check_id
        self._event = event

    async def put(self, dest_id: str, fields: Mapping[str, str]) -> None:
        self._check(dest_id)
        encoded = encode(fields)
        try:
            await asyncio.to_thread(self._backend.write, self._service, dest_id, encoded)
        except relay_keychain.KeychainWriteError as exc:
            log.warning(f"{self._event}_write_failed", dest_id=dest_id, fields=sorted(fields), reason=str(exc))
            raise SecretStoreUnavailable("the Keychain refused the write") from None
        log.info(f"{self._event}_written", dest_id=dest_id, fields=sorted(fields))

    async def get(self, dest_id: str) -> Optional[dict[str, str]]:
        self._check(dest_id)
        state, value = await asyncio.to_thread(self._backend.read_state, self._service, dest_id)
        if state == relay_keychain.READ_ABSENT:
            return None
        if state != relay_keychain.READ_OK or value is None:
            raise SecretStoreUnavailable("the Keychain could not be read")
        try:
            return decode(value)
        except CorruptSecret:
            log.warning(f"{self._event}_corrupt", dest_id=dest_id)
            raise

    async def delete(self, dest_id: str) -> bool:
        self._check(dest_id)
        removed = await asyncio.to_thread(self._backend.delete, self._service, dest_id)
        log.info(f"{self._event}_deleted", dest_id=dest_id, removed=removed)
        return removed

    async def put_verified(self, dest_id: str, fields: Mapping[str, str]) -> bool:
        try:
            await self.put(dest_id, fields)
            stored = await self.get(dest_id)
        except (SecretStoreUnavailable, CorruptSecret):
            return False
        ok = stored == dict(fields)
        if not ok:
            log.warning(f"{self._event}_verify_mismatch", dest_id=dest_id, fields=sorted(fields))
        return ok
