
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

ACME_TLS_1 = "acme-tls/1"
MAX_RECORD = 16384 + 5


class HelloError(ValueError):
    pass


@dataclass(frozen=True)
class Hello:

    sni: str
    alpn: List[str]

    @property
    def is_acme_challenge(self) -> bool:
        return self.alpn == [ACME_TLS_1]


class _Reader:

    def __init__(self, data: bytes) -> None:
        self.data, self.pos = data, 0

    def take(self, n: int) -> bytes:
        if n < 0 or self.pos + n > len(self.data):
            raise HelloError("truncated")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def num(self, n: int) -> int:
        return int.from_bytes(self.take(n), "big")


def parse(data: bytes) -> Optional[Hello]:
    if len(data) >= 1 and data[0] != 0x16:
        raise HelloError("not a handshake record")
    if len(data) < 5:
        return None
    length = int.from_bytes(data[3:5], "big")
    if length > MAX_RECORD - 5:
        raise HelloError("record too long")
    if len(data) < 5 + length:
        return None
    body = _Reader(data[5:5 + length])
    if body.num(1) != 1:
        raise HelloError("not a client hello")
    hello = _Reader(body.take(body.num(3)))
    hello.take(2 + 32)
    hello.take(hello.num(1))
    hello.take(hello.num(2))
    hello.take(hello.num(1))
    sni, alpn = "", []
    if hello.pos < len(hello.data):
        extensions = _Reader(hello.take(hello.num(2)))
        while extensions.pos < len(extensions.data):
            kind, payload = extensions.num(2), _Reader(extensions.take(extensions.num(2)))
            if kind == 0 and not sni:
                names = _Reader(payload.take(payload.num(2)))
                while names.pos < len(names.data):
                    name_type, name = names.num(1), names.take(names.num(2))
                    if name_type == 0:
                        sni = name.decode("ascii", "replace").lower().rstrip(".")
                        break
            elif kind == 16 and not alpn:
                protocols = _Reader(payload.take(payload.num(2)))
                while protocols.pos < len(protocols.data):
                    alpn.append(protocols.take(protocols.num(1)).decode("ascii", "replace"))
    return Hello(sni=sni, alpn=alpn)
