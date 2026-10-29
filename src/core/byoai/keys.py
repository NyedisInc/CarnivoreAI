
from __future__ import annotations

from typing import Optional, Protocol

from src.core import relay_keychain
from src.core.byoai.contracts import ByoaiError, InvalidKey

SERVICE = relay_keychain.BYOAI_KEY_SERVICE

MIN_HINT_LENGTH = 8


class KeychainBackend(Protocol):

    def read(self, service: str, account: str) -> Optional[str]: ...

    def state(self, service: str, account: str) -> str: ...

    def write(self, service: str, account: str, secret: str) -> None: ...

    def delete(self, service: str, account: str) -> bool: ...


class _SecurityBackend:

    def read(self, service: str, account: str) -> Optional[str]:
        return relay_keychain.read_password(service, account)

    def state(self, service: str, account: str) -> str:
        return relay_keychain.read_password_state(service, account)[0]

    def write(self, service: str, account: str, secret: str) -> None:
        relay_keychain.write_password(service, account, secret)

    def delete(self, service: str, account: str) -> bool:
        return relay_keychain.delete_password(service, account)


class KeyStore:

    def __init__(self, *, backend: Optional[KeychainBackend] = None) -> None:
        self._backend: KeychainBackend = backend or _SecurityBackend()

    def set(self, connection_id: str, key: str) -> str:
        if not relay_keychain.is_safe_secret(key) or not relay_keychain.is_safe_secret(connection_id):
            raise InvalidKey("key may only use letters, digits and _ . ~ + / = : - (no spaces or quotes)")
        try:
            self._backend.write(SERVICE, connection_id, key)
        except relay_keychain.KeychainWriteError as exc:
            raise ByoaiError(f"the Keychain refused the key: {exc}") from None
        return hint(key)

    def has(self, connection_id: str) -> bool:
        return bool(self._backend.read(SERVICE, connection_id))

    def delete(self, connection_id: str) -> bool:
        return self._backend.delete(SERVICE, connection_id)

    def confirmed_gone(self, connection_id: str) -> bool:
        return self._backend.state(SERVICE, connection_id) == relay_keychain.READ_ABSENT

    def get(self, connection_id: str) -> Optional[str]:
        return self._backend.read(SERVICE, connection_id)


def hint(key: str) -> str:
    return key[-4:] if len(key) >= MIN_HINT_LENGTH else ""
