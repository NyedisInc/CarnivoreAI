
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Dict, Optional

from src.cplugs.publicboard.headers import api_headers, as_asgi

Handler = Callable[[Any, Any, Any], Awaitable[None]]
STATES: Dict[str, int] = {"invalid": 404, "ended": 404, "limited": 429, "misrouted": 400, "unavailable": 503}
RETRY_AFTER_S = 30


async def send_body(send: Any, status: int, headers: Dict[str, str], content_type: str, body: bytes, extra: Optional[Dict[str, str]] = None) -> None:
    merged = {**headers, "Content-Type": content_type, **(extra or {})}
    wire = as_asgi(merged) + [(b"content-length", str(len(body)).encode("ascii"))]
    await send({"type": "http.response.start", "status": status, "headers": wire})
    await send({"type": "http.response.body", "body": body})


async def send_json(send: Any, status: int, payload: Dict[str, Any], extra: Optional[Dict[str, str]] = None) -> None:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    await send_body(send, status, api_headers(), "application/json", body, extra)


async def send_state(send: Any, state: str) -> None:
    extra = {"Retry-After": str(RETRY_AFTER_S)} if state == "limited" else None
    await send_json(send, STATES[state], {"state": state}, extra)
