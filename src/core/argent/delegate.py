
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

import structlog

from src.core.argent import settings as settings_module
from src.core.argent.client import ArgentClient, ArgentError, NotFound, Unauthorized, Unreachable
from src.core.argent.store import ArgentStore
from src.core.argent.token_store import TokenStore

logger = structlog.get_logger()

MINT_PATH = "/v1/my/cli/delegate"
DELEGATES_PATH = "/v1/my/cli/delegates"
REMINT_FRACTION = 0.8
LABEL_MAX = 64


class DelegateUnavailable(Exception):

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Minted:

    id: str
    expires_in: int
    token: str = field(repr=False, default="")


class Delegates:

    def __init__(self, store: ArgentStore, tokens: TokenStore, *, read_settings: Callable[[], Any] = settings_module.read, transport: Any = None,
                 clock: Callable[[], float] = time.time) -> None:
        self._store, self._tokens, self._read_settings, self._transport, self._clock = store, tokens, read_settings, transport, clock
        self._missing_logged = False

    async def _client(self) -> Optional[ArgentClient]:
        login = await asyncio.to_thread(self._store.get_login)
        cfg = await asyncio.to_thread(self._read_settings)
        token = await asyncio.to_thread(self._tokens.read, str(login["tenant_id"])) if login else None
        if not (token and cfg.server_url):
            return None
        return ArgentClient(cfg.server_url, lambda: token, ca_path=cfg.ca_path, transport=self._transport)

    async def mint(self, label: str) -> Minted:
        client = await self._client()
        if client is None:
            raise DelegateUnavailable("login")
        try:
            body = (await client.post(MINT_PATH, json={"label": label[:LABEL_MAX]})).body
        except NotFound as exc:
            if exc.body:
                raise DelegateUnavailable("failed") from None
            if not self._missing_logged:
                self._missing_logged = True
                logger.warning("argent_delegate_route_missing")
            raise DelegateUnavailable("route_missing") from None
        except Unauthorized:
            raise DelegateUnavailable("login") from None
        except ArgentError as exc:
            raise DelegateUnavailable("busy" if exc.code == "too_many_delegates" else "failed") from None
        from src.core.argent.pair_credential import TOKEN_RE  # noqa: PLC0415

        token, ident, life = body.get("access_token"), body.get("id"), body.get("expires_in")
        if not (isinstance(token, str) and TOKEN_RE.fullmatch(token) and isinstance(ident, str) and ident and isinstance(life, int) and life > 0):
            raise DelegateUnavailable("failed")
        return Minted(ident, life, token)

    async def revoke_id(self, delegate_id: str) -> bool:
        client = await self._client()
        if client is None:
            return False
        try:
            reply = await client.request("DELETE", f"{DELEGATES_PATH}/{quote(delegate_id, safe='')}")
        except NotFound:
            logger.info("argent_delegate_delete_not_found")
            return False
        except (ArgentError, Unreachable, Unauthorized):
            return False
        return reply.status == 204

    async def retire(self, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        now = self._clock()
        keep: List[Dict[str, Any]] = []
        for entry in entries:
            if float(entry["expires_at"]) / 1000 <= now:
                continue
            if not await self.revoke_id(str(entry["id"])):
                keep.append(entry)
        return keep

    async def revoke(self, install_id: str) -> None:
        rec = await asyncio.to_thread(self._store.delegate_get, install_id)
        if rec is None:
            return
        entries = ([{"id": rec["id"], "expires_at": rec["expires_at"]}] if rec.get("id") else []) + list(rec.get("stale", []))
        keep = await self.retire(entries)
        if keep:
            await asyncio.to_thread(self._store.delegate_put, install_id, {"id": "", "expires_at": 0, "remint_at": 0, "stale": keep})
        else:
            await asyncio.to_thread(self._store.delegate_drop, install_id)

    async def revoke_all(self) -> None:
        for install_id in await asyncio.to_thread(self._store.delegate_installs):
            await self.revoke(install_id)
