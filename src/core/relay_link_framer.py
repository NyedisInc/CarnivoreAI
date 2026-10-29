
from __future__ import annotations

import functools
import time
from typing import Callable, List, Optional, Union

from src.core import relay_e2ee
from src.core import relay_protocol as proto
from src.core.spectator_redaction import Scrubbed

Frame = Union[str, bytes]


@functools.lru_cache(maxsize=1)
def current_scrubber_id() -> str:
    return relay_e2ee.scrubber_id()


class PlainFramer:

    def __init__(self, link_id: str) -> None:
        self._link_id = link_id

    def grid(self, cols: int, rows: int) -> List[Frame]:
        return [proto.size_frame(self._link_id, cols, rows)]

    def data(self, data: Scrubbed) -> List[Frame]:
        return [proto.data_frame(self._link_id, piece.decode("utf-8", "replace"))
                for piece in relay_e2ee.utf8_pieces(bytes(data), relay_e2ee.MAX_BODY_BYTES)]

    paint = data

    def reopen(self) -> List[Frame]:
        return []

    def idle(self, now: float) -> List[Frame]:
        return []

    def rotate_due(self, now: float) -> bool:
        return False

    def end(self) -> List[Frame]:
        return []


class SealedFramer:

    def __init__(self, link_id: str, content_key: bytes, *, expires_at: int,
                 client_version: str, clock: Callable[[], float] = time.time) -> None:
        self._link_id = link_id
        self._sealer = relay_e2ee.Sealer(link_id, content_key, clock=clock)
        self._expires_at = expires_at
        self._version = client_version
        self._grid: Optional[tuple] = None

    def _frames(self, records: List[bytes]) -> List[Frame]:
        return [relay_e2ee.record_frame(self._link_id, record) for record in records]

    def grid(self, cols: int, rows: int) -> List[Frame]:
        self._grid = (cols, rows)
        return self._frames([self._sealer.open(
            expires_at=self._expires_at, scrubber=current_scrubber_id(),
            client_version=self._version, cols=cols, rows=rows)])

    def data(self, data: Scrubbed) -> List[Frame]:
        return self._frames(self._sealer.data(data)) if self._sealer.is_open else []

    def paint(self, data: Scrubbed) -> List[Frame]:
        return self._frames(self._sealer.paint(data)) if self._sealer.is_open else []

    def reopen(self) -> List[Frame]:
        return [] if self._grid is None else self.grid(*self._grid)

    def idle(self, now: float) -> List[Frame]:
        last = self._sealer.last_sealed_at
        if last is None or now - last < relay_e2ee.BEAT_IDLE_SECONDS:
            return []
        return self._frames([self._sealer.beat()])

    def rotate_due(self, now: float) -> bool:
        opened = self._sealer.opened_at
        return opened is not None and now - opened >= relay_e2ee.STREAM_ROTATE_SECONDS

    def end(self) -> List[Frame]:
        return self._frames([self._sealer.end()]) if self._sealer.is_open else []


LinkFramer = Union[PlainFramer, SealedFramer]


def for_link(decl: proto.LinkDeclaration, *, sealed: bool,
             client_version: str) -> Optional[LinkFramer]:
    if not sealed:
        return PlainFramer(decl.link_id)
    if decl.content_key is None or decl.expires_at is None:
        return None
    return SealedFramer(decl.link_id, decl.content_key, expires_at=decl.expires_at,
                        client_version=client_version)
