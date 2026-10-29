
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

MAX_BODY = 64 * 1024
MAX_LISTING_BODY = 2 * 1024 * 1024


class ReplyTooLarge(Exception):
    pass


@dataclass(frozen=True)
class Reply:

    status_code: int
    headers: Dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body)


async def open_connection(kind: str, target: Any) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    if kind == "unix":
        return await asyncio.open_unix_connection(str(target), limit=MAX_BODY)
    return await asyncio.open_connection("127.0.0.1", int(target), limit=MAX_BODY)


async def _read_chunked(reader: asyncio.StreamReader, max_body: int = MAX_BODY) -> bytes:
    body = b""
    while True:
        size = int((await reader.readline()).split(b";")[0].strip() or b"0", 16)
        if size == 0:
            await reader.readline()
            return body
        if len(body) + size > max_body:
            raise ReplyTooLarge("chunked body too large")
        body += await reader.readexactly(size)
        await reader.readline()


def _status_of(status_line: str) -> int:
    parts = status_line.split(" ", 2)
    if len(parts) < 2 or not parts[0].startswith("HTTP/"):
        raise ValueError("malformed status line")
    return int(parts[1])


async def exchange(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, method: str, path: str, *,
                   token: Optional[str] = None, body: Any = None, keep_alive: bool = False,
                   max_body: int = MAX_BODY, content: Optional[bytes] = None,
                   headers: Optional[Dict[str, str]] = None) -> Reply:
    if token and not token.isascii() or any(c in (token or "") + path for c in "\r\n "):
        raise ValueError("a header value or path may not carry control characters")
    extra = headers or {}
    if any(c in k + v for k, v in extra.items() for c in "\r\n"):
        raise ValueError("a header value may not carry control characters")
    data = content if content is not None else b"" if body is None else json.dumps(body).encode()
    head = [f"{method} {path} HTTP/1.1", "Host: 127.0.0.1", f"Connection: {'keep-alive' if keep_alive else 'close'}",
            f"Content-Length: {len(data)}"]
    if content is not None and not any(k.lower() == "content-type" for k in extra):
        head.append("Content-Type: application/octet-stream")
    elif body is not None:
        head.append("Content-Type: application/json")
    head.extend(f"{k}: {v}" for k, v in extra.items())
    if token:
        head.append(f"Authorization: Bearer {token}")
    writer.write(("\r\n".join(head) + "\r\n\r\n").encode() + data)
    await writer.drain()
    try:
        block = await reader.readuntil(b"\r\n\r\n")
    except asyncio.LimitOverrunError:
        raise ReplyTooLarge("header block too large") from None
    lines = block.decode("latin-1").split("\r\n")
    status = _status_of(lines[0])
    headers = {k.strip().lower(): v.strip() for k, _, v in (ln.partition(":") for ln in lines[1:] if ln)}
    if headers.get("transfer-encoding", "").lower() == "chunked":
        payload = await _read_chunked(reader, max_body)
    elif "content-length" in headers:
        length = int(headers["content-length"])
        if not 0 <= length <= max_body:
            raise ReplyTooLarge("content-length too large")
        payload = await reader.readexactly(length)
    else:
        payload = await reader.read(max_body + 1)
        if len(payload) > max_body:
            raise ReplyTooLarge("body too large")
    return Reply(status, headers, payload)
