
from __future__ import annotations

import lzma
from pathlib import Path
from typing import BinaryIO

from src.cplugs.save.engine import constants as C

try:
    from compression import zstd as _zstd
except ImportError:
    try:
        from backports import zstd as _zstd
    except ImportError:
        _zstd = None


class CodecError(RuntimeError):
    pass


def open_reader(path: Path, codec: str) -> BinaryIO:
    if codec == C.CODEC_ZSTD:
        if _zstd is None:
            raise CodecError("this point is zstd but zstd is not available here")
        return _zstd.ZstdFile(path, "rb")
    if codec == C.CODEC_LZMA:
        return lzma.open(path, "rb")
    raise CodecError(f"unknown codec {codec!r}")
