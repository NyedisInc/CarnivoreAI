
from __future__ import annotations

from fastapi import HTTPException, Request, UploadFile

CHUNK_BYTES: int = 64 * 1024


def _too_large(what: str, max_bytes: int) -> HTTPException:
    return HTTPException(status_code=413, detail=f"{what} exceeds the maximum upload size of {max_bytes // (1024 * 1024)} MB")


async def read_capped_upload(file: UploadFile, max_bytes: int, what: str = "image") -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise _too_large(what, max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)


async def read_capped_body(request: Request, max_bytes: int, what: str = "audio") -> bytes:
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    if declared > max_bytes:
        raise _too_large(what, max_bytes)
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise _too_large(what, max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)
