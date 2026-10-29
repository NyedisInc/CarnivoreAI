
from __future__ import annotations

import lzma
from typing import Dict

try:
    from compression import zstd as _zstd
except ImportError:
    try:
        from backports import zstd as _zstd
    except ImportError:
        _zstd = None

CODEC_ZSTD: str = "zstd"
CODEC_LZMA: str = "lzma"
BLOB_EXTENSIONS: Dict[str, str] = {CODEC_ZSTD: ".zst", CODEC_LZMA: ".xz"}
ZSTD_LEVEL: int = 6
LZMA_PRESET: int = 6
BLOBS_PREFIX: str = "blobs"

_STREAM_ERRORS = (lzma.LZMAError, getattr(_zstd, "ZstdError", lzma.LZMAError))


class CodecUnavailable(ValueError):
    pass


class BlobMissing(FileNotFoundError):
    pass


class BlobCorrupt(RuntimeError):
    pass


def default_codec() -> str:
    return CODEC_ZSTD if _zstd is not None else CODEC_LZMA


def compress(raw: bytes, codec: str) -> bytes:
    if codec == CODEC_ZSTD:
        if _zstd is None:
            raise ValueError("zstd is not available on this interpreter")
        return _zstd.compress(raw, level=ZSTD_LEVEL)
    if codec == CODEC_LZMA:
        return lzma.compress(raw, preset=LZMA_PRESET)
    raise ValueError(f"unknown codec {codec!r}")


def decompress(packed: bytes, codec: str) -> bytes:
    try:
        if codec == CODEC_ZSTD:
            if _zstd is None:
                raise CodecUnavailable("this blob is zstd but zstd is not available here")
            return _zstd.decompress(packed)
        if codec == CODEC_LZMA:
            return lzma.decompress(packed)
    except _STREAM_ERRORS as exc:
        raise BlobCorrupt(f"not a valid {codec} stream: {exc}") from exc
    raise ValueError(f"unknown codec {codec!r}")


def decompress_bounded(packed: bytes, codec: str, max_length: int) -> bytes:
    if max_length < 0:
        raise ValueError("max_length must not be negative")
    if codec == CODEC_ZSTD:
        if _zstd is None:
            raise CodecUnavailable("this blob is zstd but zstd is not available here")
        decomp = _zstd.ZstdDecompressor()
    elif codec == CODEC_LZMA:
        decomp = lzma.LZMADecompressor()
    else:
        raise ValueError(f"unknown codec {codec!r}")
    try:
        out = decomp.decompress(packed, max_length + 1)
    except _STREAM_ERRORS as exc:
        raise BlobCorrupt(f"not a valid {codec} stream: {exc}") from exc
    if len(out) > max_length:
        raise BlobCorrupt(f"{codec} stream inflates past its stated length of {max_length} bytes")
    if not decomp.eof:
        # not allowed
        raise BlobCorrupt(f"{codec} stream is truncated or longer than its stated length of {max_length} bytes")
    if decomp.unused_data:
        raise BlobCorrupt(f"{codec} stream has {len(decomp.unused_data)} bytes after its end")
    return out


def blob_relpath(sha: str, codec: str) -> str:
    return f"{BLOBS_PREFIX}/{sha[:2]}/{sha}{BLOB_EXTENSIONS[codec]}"


def codec_library() -> str:
    if _zstd is None:
        return CODEC_LZMA
    return ".".join(map(str, _zstd.zstd_version_info))
