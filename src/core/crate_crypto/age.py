
from __future__ import annotations

import io
import os
from collections import OrderedDict
from typing import BinaryIO, Callable, Optional, Sequence

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from src.core.crate_crypto.age_header import FILE_KEY_BYTES, MAX_HEADER_BYTES, build_header, hkdf, open_file_key, parse_header
from src.core.crate_crypto.errors import Corrupt, Malformed, WrongKey

CHUNK_BYTES: int = 64 * 1024
TAG_BYTES: int = 16
SEALED_CHUNK_BYTES: int = CHUNK_BYTES + TAG_BYTES
NONCE_BYTES: int = 16
PAYLOAD_INFO: bytes = b"payload"
CACHE_CHUNKS: int = 4
_MAX_COUNTER: int = 1 << 88
_FLAG_LAST: bytes = b"\x01"
_FLAG_MORE: bytes = b"\x00"


def _chunk_nonce(index: int, last: bool) -> bytes:
    return index.to_bytes(11, "big") + (_FLAG_LAST if last else _FLAG_MORE)


class AgeWriter(io.RawIOBase):

    def __init__(self, raw: BinaryIO, recipients: Sequence[bytes], *, _rng: Callable[[int], bytes] = os.urandom) -> None:
        super().__init__()
        self._raw = raw
        self._aborted = False
        file_key = _rng(FILE_KEY_BYTES)
        header = build_header(recipients, file_key, _rng)
        nonce = _rng(NONCE_BYTES)
        self._aead = ChaCha20Poly1305(hkdf(file_key, nonce, PAYLOAD_INFO))
        self._counter = 0
        self._buf = bytearray()
        raw.write(header + nonce)

    def writable(self) -> bool:
        return True

    def _seal(self, data: bytes, last: bool) -> None:
        if self._counter >= _MAX_COUNTER:
            raise OverflowError("age STREAM counter exhausted")
        self._raw.write(self._aead.encrypt(_chunk_nonce(self._counter, last), data, None))
        self._counter += 1

    def write(self, b: bytes) -> int:
        if self.closed:
            raise ValueError("write to a closed AgeWriter")
        self._buf += b
        while len(self._buf) > CHUNK_BYTES:
            self._seal(bytes(self._buf[:CHUNK_BYTES]), False)
            del self._buf[:CHUNK_BYTES]
        return len(b)

    def abort(self) -> None:
        self._aborted = True
        super().close()

    def close(self) -> None:
        if self.closed:
            return
        if not self._aborted:
            self._seal(bytes(self._buf), True)
            self._buf.clear()
        super().close()

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            self.abort()
        else:
            self.close()

    def __del__(self) -> None:
        if not self.closed:
            self.abort()


class AgeReader(io.RawIOBase):

    def __init__(self, raw: BinaryIO, identities: Sequence[bytes], *, start: int = 0, length: Optional[int] = None) -> None:
        super().__init__()
        if length is None:
            length = raw.seek(0, io.SEEK_END) - start
        raw.seek(start)
        header = parse_header(raw.read(min(length, MAX_HEADER_BYTES)))
        if not identities:
            raise WrongKey("no identity was given to open this age file")
        file_key = open_file_key(header, identities)
        if length - header.length < NONCE_BYTES:
            raise Malformed("the age payload nonce is missing")
        raw.seek(start + header.length)
        nonce = raw.read(NONCE_BYTES)
        if len(nonce) != NONCE_BYTES:
            raise Malformed("the age payload nonce is missing")
        self._raw = raw
        self._aead = ChaCha20Poly1305(hkdf(file_key, nonce, PAYLOAD_INFO))
        self._base = start + header.length + NONCE_BYTES
        sealed = length - header.length - NONCE_BYTES
        self._chunks = -(-sealed // SEALED_CHUNK_BYTES)
        self._last_len = sealed - (self._chunks - 1) * SEALED_CHUNK_BYTES if self._chunks else 0
        self._tail_error: Optional[str] = None
        if self._chunks == 0:
            self._tail_error = "the age payload has no chunks"
        elif self._last_len < TAG_BYTES:
            self._tail_error = "the final age payload chunk is truncated"
        full = max(self._chunks - 1, 0) * CHUNK_BYTES
        self.size = full if self._tail_error else full + self._last_len - TAG_BYTES
        self._pos = 0
        self._cache: "OrderedDict[int, bytes]" = OrderedDict()

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._pos, io.SEEK_END: self.size}.get(whence)
        if base is None:
            raise ValueError(f"invalid whence {whence}")
        if base + offset < 0:
            raise ValueError("negative seek position")
        self._pos = base + offset
        return self._pos

    def _chunk(self, index: int) -> bytes:
        if index in self._cache:
            self._cache.move_to_end(index)
            return self._cache[index]
        last = index == self._chunks - 1
        want = self._last_len if last else SEALED_CHUNK_BYTES
        self._raw.seek(self._base + index * SEALED_CHUNK_BYTES)
        sealed = self._raw.read(want)
        if len(sealed) != want:
            raise Corrupt("the age file is shorter than it was when opened")
        plain = self._open(index, last, sealed)
        if plain is None and want == SEALED_CHUNK_BYTES:
            plain = self._open(index, not last, sealed)
            if plain is not None:
                self._tail_error = ("the age payload has no final chunk" if last
                                    else "the age payload has data after its final chunk")
                self.size = min(self.size, index * CHUNK_BYTES + len(plain))
        if plain is None:
            raise Corrupt(f"age payload chunk {index} fails authentication")
        if last and not plain and index > 0:
            raise Corrupt("the final age payload chunk is empty")
        self._cache[index] = plain
        if len(self._cache) > CACHE_CHUNKS:
            self._cache.popitem(last=False)
        return plain

    def _open(self, index: int, last: bool, sealed: bytes) -> Optional[bytes]:
        try:
            return self._aead.decrypt(_chunk_nonce(index, last), sealed, None)
        except InvalidTag:
            return None

    def _check_end(self) -> None:
        if self._tail_error is None and self._chunks:
            self._chunk(self._chunks - 1)
        if self._tail_error is not None:
            raise Corrupt(self._tail_error)

    def readinto(self, b) -> int:
        view = memoryview(b).cast("B")
        done = 0
        while done < len(view):
            if self._pos >= self.size:
                if not done:
                    self._check_end()
                break
            index, offset = divmod(self._pos, CHUNK_BYTES)
            piece = self._chunk(index)[offset:offset + len(view) - done]
            if not piece:
                continue
            view[done:done + len(piece)] = piece
            done += len(piece)
            self._pos += len(piece)
        return done

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            out = bytearray()
            while True:
                piece = self.read(CHUNK_BYTES)
                if not piece:
                    return bytes(out)
                out += piece
        buf = bytearray(size)
        return bytes(buf[:self.readinto(buf)])
