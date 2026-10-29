
from __future__ import annotations

import hashlib
from typing import Callable, Dict, List, Optional

from relay.protocol import WATCH_SUBPROTOCOL

STUB_SECRET = "testsecretnotreal-0123456789ABCDEF"
STUB_REPLACEMENT = "*" * len(STUB_SECRET)


class StubRedactor:

    def __init__(self, tail: int = 0) -> None:
        self.fed: List[str] = []
        self.flush_calls = 0
        self._tail = tail
        self._held = ""

    def feed(self, chunk: str) -> str:
        self.fed.append(chunk)
        self._held += chunk.replace(STUB_SECRET, STUB_REPLACEMENT)
        if self._tail <= 0:
            out, self._held = self._held, ""
            return out
        if len(self._held) <= self._tail:
            return ""
        out = self._held[: -self._tail]
        self._held = self._held[-self._tail :]
        return out

    def flush(self) -> str:
        self.flush_calls += 1
        out, self._held = self._held, ""
        return out


class RecordingFactory:

    def __init__(self, tail: int = 0) -> None:
        self.tail = tail
        self.made: List[StubRedactor] = []

    def __call__(self) -> StubRedactor:
        redactor = StubRedactor(tail=self.tail)
        self.made.append(redactor)
        return redactor


def sha256_of(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


PUBLISHER_ID = "p" * 32


def links_frame(
    entries: Dict[str, str], session: str = "ses_1", publisher: str = PUBLISHER_ID
) -> dict:
    return {
        "type": "links",
        "publisher_id": publisher,
        "links": [
            {
                "link_id": link_id,
                "token_sha256": sha256_of(token),
                "session_id": session,
            }
            for link_id, token in entries.items()
        ],
    }


def data_frame(link_id: str, payload: str) -> dict:
    return {"type": "data", "link_id": link_id, "payload": payload}


def watch_protocols(token: str) -> List[str]:
    return [WATCH_SUBPROTOCOL, token]


class RecordingHmac:

    def __init__(self, compare: Callable[[bytes, bytes], bool]) -> None:
        self._compare = compare
        self.calls: List[tuple] = []

    def compare_digest(self, left: bytes, right: bytes) -> bool:
        self.calls.append((left, right))
        return self._compare(left, right)

    def saw(self, left: bytes, right: Optional[bytes] = None) -> bool:
        for seen_left, seen_right in self.calls:
            if seen_left != left:
                continue
            if right is None or seen_right == right:
                return True
        return False
