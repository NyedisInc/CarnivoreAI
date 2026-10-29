
from __future__ import annotations

import hashlib
import json
import secrets
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from src.core.relay_identity.device_key import b64url, unb64url
from src.core.spectator_redaction import Scrubbed

VERSION = 0x02

KIND_OPEN = 1
KIND_DATA = 2
KIND_BEAT = 3
KIND_END = 4
KIND_PAINT = 5

INFO_WATCH_AUTH = b"carnivore relay v2 watch-auth"
INFO_CONTENT_KEY = b"carnivore relay v2 content-key"
INFO_STREAM_KEY = b"carnivore relay v2 stream-key"
AAD_PREFIX = b"carnivore-relay-v2"

TOKEN_BYTES = 32
STREAM_ID_BYTES = 16
TAG_BYTES = 16

HEADER_BYTES = 1 + STREAM_ID_BYTES + 8

PLAIN_PREFIX_BYTES = 1 + 8

MIN_RECORD_BYTES = HEADER_BYTES + PLAIN_PREFIX_BYTES + TAG_BYTES

MAX_BODY_BYTES = 16 * 1024

BEAT_IDLE_SECONDS = 5.0

STREAM_ROTATE_SECONDS = 300.0

_SCRUBBER_GLOBS = ("message_model_secret*.py", "stream_redactor*.py")


class E2eeError(ValueError):
    pass


def _hkdf(ikm: bytes, salt: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(ikm)


def token_bytes(token: str) -> bytes:
    raw = unb64url(token, TOKEN_BYTES)
    if raw is None:
        raise E2eeError("share token must be exactly 32 bytes of unpadded base64url")
    return raw


@dataclass(frozen=True)
class LinkKeys:

    watch_auth: bytes = field(repr=False)
    content_key: bytes = field(repr=False)

    @property
    def verifier(self) -> str:
        return watch_verifier(self.watch_auth)


def derive_link_keys(token: str, link_id: str) -> LinkKeys:
    ikm = token_bytes(token)
    salt = link_id.encode("utf-8")
    return LinkKeys(watch_auth=_hkdf(ikm, salt, INFO_WATCH_AUTH),
                    content_key=_hkdf(ikm, salt, INFO_CONTENT_KEY))


def watch_verifier(watch_auth: bytes) -> str:
    return hashlib.sha256(watch_auth).hexdigest()


def stream_key(content_key: bytes, stream_id: bytes) -> bytes:
    if len(content_key) != 32 or len(stream_id) != STREAM_ID_BYTES:
        raise E2eeError("content key must be 32 bytes and stream id 16")
    return _hkdf(content_key, stream_id, INFO_STREAM_KEY)


def record_aad(link_id: str, stream_id: bytes, seq: int) -> bytes:
    lid = link_id.encode("utf-8")
    if not 0 < len(lid) < 256:
        raise E2eeError("link id must be 1 to 255 bytes")
    return (AAD_PREFIX + bytes([len(lid)]) + lid + bytes([VERSION])
            + stream_id + struct.pack(">Q", seq))


def _nonce(seq: int) -> bytes:
    return b"\x00\x00\x00\x00" + struct.pack(">Q", seq)


def seal_record(content_key: bytes, link_id: str, stream_id: bytes, seq: int,
                kind: int, ts_ms: int, body: bytes) -> bytes:
    return _seal_with(AESGCM(stream_key(content_key, stream_id)), link_id, stream_id,
                      seq, kind, ts_ms, body)


def _seal_with(aead: AESGCM, link_id: str, stream_id: bytes, seq: int,
               kind: int, ts_ms: int, body: bytes) -> bytes:
    if not 0 <= seq < 1 << 64:
        raise E2eeError("seq out of range")
    plain = bytes([kind]) + struct.pack(">Q", ts_ms) + body
    sealed = aead.encrypt(_nonce(seq), plain, record_aad(link_id, stream_id, seq))
    return bytes([VERSION]) + stream_id + struct.pack(">Q", seq) + sealed


@dataclass(frozen=True)
class OpenedRecord:

    stream_id: bytes
    seq: int
    kind: int
    ts_ms: int
    body: bytes


def open_record(content_key: bytes, link_id: str, record: bytes) -> OpenedRecord:
    if len(record) < MIN_RECORD_BYTES or record[0] != VERSION:
        raise E2eeError("not a v2 record")
    stream_id = record[1:1 + STREAM_ID_BYTES]
    (seq,) = struct.unpack(">Q", record[1 + STREAM_ID_BYTES:HEADER_BYTES])
    try:
        plain = AESGCM(stream_key(content_key, stream_id)).decrypt(
            _nonce(seq), record[HEADER_BYTES:], record_aad(link_id, stream_id, seq))
    except Exception as exc:  # noqa: BLE001
        raise E2eeError("record failed authentication") from exc
    (ts_ms,) = struct.unpack(">Q", plain[1:PLAIN_PREFIX_BYTES])
    return OpenedRecord(stream_id, seq, plain[0], ts_ms, plain[PLAIN_PREFIX_BYTES:])


def open_body(expires_at: int, scrubber: str, client_version: str,
              cols: int, rows: int, prev: Optional[dict] = None) -> bytes:
    return json.dumps({"client_version": client_version, "cols": cols,
                       "expires_at": expires_at, "prev": prev, "rows": rows,
                       "scrubber_id": scrubber},
                      separators=(",", ":"), sort_keys=True).encode("utf-8")


class Sealer:

    def __init__(self, link_id: str, content_key: bytes, *,
                 clock: Callable[[], float] = time.time,
                 random: Callable[[int], bytes] = secrets.token_bytes) -> None:
        if len(content_key) != 32:
            raise E2eeError("content key must be 32 bytes")
        record_aad(link_id, bytes(STREAM_ID_BYTES), 0)
        self._link_id = link_id
        self._key = content_key
        self._clock = clock
        self._random = random
        self._stream: Optional[bytes] = None
        self._aead: Optional[AESGCM] = None
        self._seq = 0
        self.opened_at: Optional[float] = None
        self.last_sealed_at: Optional[float] = None

    @property
    def is_open(self) -> bool:
        return self._stream is not None

    def _seal(self, kind: int, body: bytes) -> bytes:
        if self._stream is None or self._aead is None:
            raise E2eeError("no stream: seal OPEN first")
        now = self._clock()
        record = _seal_with(self._aead, self._link_id, self._stream, self._seq,
                            kind, int(now * 1000), body)
        self._seq += 1
        self.last_sealed_at = now
        return record

    def open(self, *, expires_at: int, scrubber: str, client_version: str,
             cols: int, rows: int) -> bytes:
        prev = (None if self._stream is None
                else {"stream": self._stream.hex(), "seq": self._seq - 1})
        stream = self._random(STREAM_ID_BYTES)
        if len(stream) != STREAM_ID_BYTES:
            raise E2eeError("stream id must be 16 bytes")
        self._stream = stream
        self._aead = AESGCM(stream_key(self._key, stream))
        self._seq = 0
        self.opened_at = self._clock()
        return self._seal(KIND_OPEN, open_body(expires_at, scrubber, client_version,
                                               cols, rows, prev))

    def _scrubbed_records(self, kind: int, data: Scrubbed) -> List[bytes]:
        if type(data) is not Scrubbed:
            raise TypeError("only a scrubber's output may be sealed")
        return [self._seal(kind, piece) for piece in utf8_pieces(bytes(data), MAX_BODY_BYTES)]

    def data(self, data: Scrubbed) -> List[bytes]:
        return self._scrubbed_records(KIND_DATA, data)

    def paint(self, data: Scrubbed) -> List[bytes]:
        return self._scrubbed_records(KIND_PAINT, data)

    def beat(self) -> bytes:
        return self._seal(KIND_BEAT, b"")

    def end(self) -> bytes:
        return self._seal(KIND_END, b"")


def utf8_pieces(data: bytes, limit: int) -> List[bytes]:
    pieces: List[bytes] = []
    start = 0
    while start < len(data):
        end = min(start + limit, len(data))
        if end < len(data):
            cut = end
            while cut > start and (data[cut] & 0xC0) == 0x80:
                cut -= 1
            end = cut if cut > start else end
        pieces.append(data[start:end])
        start = end
    return pieces


def record_frame(link_id: str, record: bytes) -> bytes:
    lid = link_id.encode("ascii")
    if not 0 < len(lid) <= 128:
        raise E2eeError("link id must be 1 to 128 ascii bytes")
    return bytes([len(lid)]) + lid + record


def scrubber_id(root: Optional[Path] = None) -> str:
    base = root or Path(__file__).resolve().parent
    paths = sorted({p for pattern in _SCRUBBER_GLOBS for p in base.glob(pattern)},
                   key=lambda p: p.name)
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode() + b"\x00" + path.read_bytes() + b"\x00")
    return digest.hexdigest()[:12]


FRAGMENT_PREFIX = "v2."


def share_fragment(token: str, e2ee: bool) -> str:
    return f"{FRAGMENT_PREFIX}{token}" if e2ee else token
