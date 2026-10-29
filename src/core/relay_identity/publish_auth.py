
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Optional, Tuple

import structlog

from src.core import relay_protocol as proto
from src.core.relay_identity import device_key as dk
from src.core.relay_identity.session import (
    REFRESH_MARGIN_SECONDS,
    DeviceSession,
    RelayAuthError,
    RelayToken,
)

logger = structlog.get_logger()

PUBLISH_SUBPROTOCOL_V2 = "carnivore.relay.publish.v2"


@dataclass(frozen=True)
class Dial:

    subprotocol: str
    headers: Dict[str, str]


class LegacyAuth:

    version = 1

    def __init__(self, token: str) -> None:
        self._token = token

    async def dial(self) -> Dial:
        return Dial(proto.PUBLISH_SUBPROTOCOL, {"Authorization": f"Bearer {self._token}"})

    def declarable(self, decl: proto.LinkDeclaration) -> bool:
        return decl.nonce is None

    def links_frame(self, decls: Iterable[proto.LinkDeclaration], publisher_id: str) -> str:
        return proto.links_frame(decls, publisher_id)

    def reauth_due(self) -> bool:
        return False

    async def reauth_frame(self) -> str:
        raise RuntimeError("v1 has no reauth")

    def new_link_identity(self) -> Optional[Tuple[str, str]]:
        return None

    def invalidate(self) -> None:
        pass


class DeviceAuth:

    version = 2

    def __init__(self, session: DeviceSession, clock: Callable[[], float] = time.time) -> None:
        self._session = session
        self._clock = clock
        self._exp = 0

    async def dial(self) -> Dial:
        token = await self._session.token()
        self._exp = token.exp
        return Dial(PUBLISH_SUBPROTOCOL_V2, await self._session.pop_headers(token))

    def declarable(self, decl: proto.LinkDeclaration) -> bool:
        nonce = dk.unb64url(decl.nonce, 16)
        device_id = self._session.device_id
        return (nonce is not None and device_id is not None
                and decl.content_key is not None
                and dk.link_id_for(device_id, nonce) == decl.link_id)

    def links_frame(self, decls: Iterable[proto.LinkDeclaration], publisher_id: str) -> str:
        return json.dumps({"type": "links", "links": [
            {"link_id": d.link_id, "token_sha256": d.token_sha256, "nonce": d.nonce,
             **({} if d.expires_at is None else {"expires_at": d.expires_at})}
            for d in decls]})

    def reauth_due(self) -> bool:
        return self._clock() >= self._exp - REFRESH_MARGIN_SECONDS

    async def reauth_frame(self) -> str:
        token: RelayToken = await self._session.token()
        self._exp = token.exp
        return json.dumps(await self._session.reauth_frame(token))

    def new_link_identity(self) -> Optional[Tuple[str, str]]:
        return self._session.new_link_identity()

    def invalidate(self) -> None:
        self._session.drop_token()


PublishAuth = LegacyAuth | DeviceAuth


async def resolve(
    session: Optional[DeviceSession], legacy_token: Callable[[], Optional[str]],
    legacy_fallback: bool = True,
) -> PublishAuth:
    failure: Optional[RelayAuthError] = None
    if session is not None:
        try:
            await session.token()
            return DeviceAuth(session)
        except RelayAuthError as exc:
            if exc.terminal or exc.parks:
                raise
            failure = exc
    fallback = await asyncio.to_thread(legacy_token) if legacy_fallback else None
    if fallback:
        logger.info("relay_publish_legacy_fallback",
                    reason=failure.kind if failure else "device_identity_off")
        return LegacyAuth(fallback)
    raise failure or RelayAuthError("refused", "no device identity and no legacy token")

