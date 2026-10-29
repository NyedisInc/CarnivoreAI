
from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import Any, Deque, Dict, Optional

import structlog
from starlette.websockets import WebSocketDisconnect

logger = structlog.get_logger()

MAX_TEXT_QUEUE = 256

OVERFLOW_CLOSE_CODE = 4429


class Viewer:

    def __init__(self, websocket: Any) -> None:
        self._ws = websocket
        self._texts: Deque[str] = deque()
        self._frame: Optional[bytes] = None
        self._wake = asyncio.Event()
        self._close_code: Optional[int] = None
        self._close_reason = ""

    def offer_text(self, message: Dict[str, Any]) -> None:
        if self._close_code is not None:
            return
        if len(self._texts) >= MAX_TEXT_QUEUE:
            self.close(OVERFLOW_CLOSE_CODE, "viewer fell behind")
            return
        self._texts.append(json.dumps(message))
        self._wake.set()

    def offer_frame(self, jpeg: bytes) -> None:
        self._frame = jpeg
        self._wake.set()

    def close(self, code: int = 1000, reason: str = "") -> None:
        if self._close_code is None:
            self._close_code, self._close_reason = code, reason
        self._wake.set()

    async def run(self) -> None:
        try:
            while True:
                await self._wake.wait()
                self._wake.clear()
                while self._texts and self._close_code != OVERFLOW_CLOSE_CODE:
                    await self._ws.send_text(self._texts.popleft())
                if self._close_code is not None:
                    await self._ws.close(code=self._close_code, reason=self._close_reason)
                    return
                frame, self._frame = self._frame, None
                if frame is not None:
                    await self._ws.send_bytes(frame)
        except (RuntimeError, OSError, WebSocketDisconnect) as exc:
            logger.debug("browser_viewer_send_ended", error=type(exc).__name__)
