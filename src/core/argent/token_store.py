
from __future__ import annotations

from typing import Any, Dict, Optional

from src.core import relay_keychain

SERVICE = relay_keychain.ARGENT_CLI_SERVICE


class TokenUnavailable(RuntimeError):
    pass


class TokenStore:

    def __init__(self, backend: Any = relay_keychain) -> None:
        self._backend = backend

    def pointer(self, tenant_id: str) -> Dict[str, str]:
        return {"service": SERVICE, "account": tenant_id}

    def write(self, tenant_id: str, token: str) -> None:
        try:
            self._backend.write_password(SERVICE, tenant_id, token, True)
        except relay_keychain.KeychainWriteError as exc:
            raise TokenUnavailable("the login token could not be stored in the keychain") from exc

    def read(self, tenant_id: str) -> Optional[str]:
        return self._backend.read_password(SERVICE, tenant_id)

    def delete(self, tenant_id: str) -> bool:
        return bool(self._backend.delete_password(SERVICE, tenant_id))
