
from __future__ import annotations

import base64
import binascii
import collections
import json
import threading
import time
from typing import Any, Callable, Deque, Dict, Optional, Tuple

import structlog

from src.core.pack.machines import roster_v2

logger = structlog.get_logger(__name__)

PIECE_BYTES = 8 * 1024
MAX_PIECES = 96
REJECTED_SHAS = 16
STALL_SECONDS = 60.0
_SHA_LEN = 64


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == _SHA_LEN and all(c in "0123456789abcdef" for c in value)


def _int(value: Any, hi: int) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= hi else None


def _head(raw: Any) -> Optional[Tuple[int, int, str]]:
    if not isinstance(raw, dict):
        return None
    gen, at = _int(raw.get("generation"), 2 ** 62), _int(raw.get("issued_at"), 2 ** 62)
    return (gen, at, raw["sha256"]) if gen is not None and at is not None and _is_sha(raw.get("sha256")) else None


class Courier:

    def __init__(self, held: Callable[[], Optional[Dict[str, Any]]], merge: Callable[[Any, str], bool]) -> None:
        self._held, self._merge = held, merge
        self._lock = threading.Lock()
        self._mine: Optional[Tuple[Tuple[Any, ...], bytes, Tuple[int, int, str]]] = None
        self._memo: Dict[str, Dict[str, Any]] = {}
        self._rejected: Deque[str] = collections.deque(maxlen=REJECTED_SHAS)
        self._asm: Optional[Dict[str, Any]] = None

    def _own(self) -> Optional[Tuple[bytes, Tuple[int, int, str]]]:
        wire = self._held()
        if wire is None:
            return None
        body = wire.get("roster") or {}
        key = (body.get("generation"), body.get("issued_at"), (wire.get("sig") or {}).get("sig"))
        if self._mine is None or self._mine[0] != key:
            data = roster_v2.blob(wire)
            ok = len(data) <= roster_v2.MAX_BLOB_BYTES
            self._mine = (key, data, (int(key[0]), int(key[1]), roster_v2.sha(data)) if ok else None)  # type: ignore[arg-type]
        return (self._mine[1], self._mine[2]) if self._mine[2] is not None else None

    def outgoing(self, peer_id: str, peer_part: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        with self._lock:
            own = self._own()
            theirs = peer_part if isinstance(peer_part, dict) else self._memo.get(peer_id, {})
            head, want = _head(theirs.get("head")), theirs.get("want")
            out: Dict[str, Any] = {"head": None, "want": None, "piece": None}
            if self._asm is not None:
                out["want"] = {"sha256": self._asm["head"][2], "index": len(self._asm["pieces"])}
            if own is None:
                return out
            data, mine = own
            out["head"] = {"generation": mine[0], "issued_at": mine[1], "sha256": mine[2]}
            if head is None or head[:2] < mine[:2]:
                index = _int(want.get("index"), MAX_PIECES) if isinstance(want, dict) and want.get("sha256") == mine[2] else 0
                count = max(1, -(-len(data) // PIECE_BYTES))
                if index is not None and index < count:
                    chunk = data[index * PIECE_BYTES:(index + 1) * PIECE_BYTES]
                    out["piece"] = {"sha256": mine[2], "index": index, "count": count, "data": base64.b64encode(chunk).decode()}
            return out

    def incoming(self, peer_id: str, part: Any) -> bool:
        if not isinstance(part, dict):
            return False
        with self._lock:
            self._memo[peer_id] = {"head": part.get("head"), "want": part.get("want")}
            if len(self._memo) > 256:
                self._memo.pop(next(iter(self._memo)))
            head, piece = _head(part.get("head")), part.get("piece")
            if head is None or not isinstance(piece, dict) or piece.get("sha256") != head[2] or head[2] in self._rejected:
                return False
            held = self._own()
            if held is not None and head[:2] <= held[1][:2]:
                return False
            index, count = _int(piece.get("index"), MAX_PIECES), _int(piece.get("count"), MAX_PIECES)
            chunk = self._chunk(piece.get("data"))
            if index is None or count is None or count < 1 or index >= count or chunk is None:
                return False
            asm, now = self._asm, time.monotonic()
            if asm is not None and now - asm["at"] > STALL_SECONDS:
                asm = self._asm = None
            if asm is not None and asm["head"][2] != head[2]:
                if head[:2] <= asm["head"][:2]:
                    return False
                asm = self._asm = None
            if asm is None:
                asm = self._asm = {"head": head, "count": count, "pieces": [], "at": now}
            if index != len(asm["pieces"]) or count != asm["count"]:
                return False
            asm["pieces"].append(chunk)
            asm["at"] = now
            if len(asm["pieces"]) < count:
                return False
            self._asm = None
            data = b"".join(asm["pieces"])
        return self._finish(peer_id, head, data)

    @staticmethod
    def _chunk(data: Any) -> Optional[bytes]:
        if not isinstance(data, str) or len(data) > PIECE_BYTES * 2:
            return None
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            return None
        return raw if 0 < len(raw) <= PIECE_BYTES else None

    def _finish(self, peer_id: str, head: Tuple[int, int, str], data: bytes) -> bool:
        wire: Any = None
        if len(data) <= roster_v2.MAX_BLOB_BYTES and roster_v2.sha(data) == head[2]:
            try:
                wire = json.loads(data)
            except ValueError:
                wire = None
        taken = wire is not None and self._merge(wire, peer_id)
        if not taken:
            with self._lock:
                self._rejected.append(head[2])
            logger.info("pack_roster_v2_piece_refused", sender=peer_id[:8], sha=head[2][:12], size=len(data))
        return taken
