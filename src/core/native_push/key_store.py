
from __future__ import annotations

from typing import Optional

from src.core import relay_keychain
from src.core.notifications.destinations import secrets as secret_store


class PayloadKeyStore(secret_store.DestinationSecrets):

    def __init__(self, *, backend: Optional[secret_store.KeychainBackend] = None) -> None:
        super().__init__(backend=backend, service=relay_keychain.NATIVE_PUSH_SERVICE)
        self._legacy = secret_store.DestinationSecrets(backend=backend, service=relay_keychain.NOTIFICATIONS_SERVICE)

    async def get(self, dest_id: str) -> Optional[dict[str, str]]:
        found = await super().get(dest_id)
        if found is not None:
            return found
        old = await self._legacy.get(dest_id)
        if old is None:
            return None
        await self.put(dest_id, old)
        if await super().get(dest_id) == old:
            await self._legacy.delete(dest_id)
        return old

    async def delete(self, dest_id: str) -> bool:
        gone = await super().delete(dest_id)
        return await self._legacy.delete(dest_id) or gone
