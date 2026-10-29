
from __future__ import annotations

from typing import Awaitable, Callable, Optional, Protocol

from src.core.federation.peer_client import PeerClient, Route


class Transport(Protocol):

    out_path: str
    settle: Optional[Callable[[], Awaitable[None]]]

    async def establish(self) -> Route:
        ...

    async def renew(self, client: PeerClient) -> None:
        ...

    async def close(self) -> None:
        ...
