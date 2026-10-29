
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.api import ai_invoke_routes, session_input_routes

CHUNK = 10_000
TOTAL_CHUNKS = 200


class Pulled:

    def __init__(self) -> None:
        self.chunks = 0


def _request(pulled: Pulled, headers: List[tuple[bytes, bytes]]) -> Request:
    queue = [{"type": "http.request", "body": b"x" * CHUNK, "more_body": i < TOTAL_CHUNKS - 1} for i in range(TOTAL_CHUNKS)]

    async def receive() -> Dict[str, Any]:
        if not queue:
            return {"type": "http.disconnect"}
        pulled.chunks += 1
        return queue.pop(0)

    scope = {"type": "http", "method": "POST", "path": "/", "headers": headers, "query_string": b"", "app": None}
    return Request(scope, receive)


def test_transcribe_stops_reading_at_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_invoke_routes, "MAX_AUDIO_BYTES", 5 * CHUNK)
    pulled = Pulled()
    request = _request(pulled, [(b"content-type", b"audio/wav")])
    with pytest.raises(HTTPException) as err:
        asyncio.run(ai_invoke_routes.transcribe(request, feature="f"))
    assert err.value.status_code == 413
    assert pulled.chunks <= 7, f"read {pulled.chunks} of {TOTAL_CHUNKS} chunks past a 5 chunk cap"


class FakeUpload:

    filename = "big.bin"
    content_type = "application/octet-stream"

    def __init__(self) -> None:
        self.served = 0

    async def read(self, size: int = -1) -> bytes:
        n = 20 * 1024 * 1024 if size < 0 else size
        self.served += n
        return b"\0" * n if self.served <= 20 * 1024 * 1024 else b""


def test_upload_file_stops_reading_at_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    session = SimpleNamespace(id="ses_a", working_dir="/tmp")
    registry = SimpleNamespace(get_session=lambda sid: session, current_session=lambda: session)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(
            session_manager=SimpleNamespace(has_active_session=lambda: True),
            services=SimpleNamespace(registry=registry))),
        state=SimpleNamespace())
    monkeypatch.setattr(session_input_routes, "refuse_remote", lambda *a, **k: None)
    cfg = SimpleNamespace(uploads=SimpleNamespace(max_size_mb=1, max_file_size_mb=1))
    monkeypatch.setattr(session_input_routes, "settings", SimpleNamespace(load_auth_config=lambda: cfg))
    upload = FakeUpload()
    with pytest.raises(HTTPException) as err:
        asyncio.run(session_input_routes.upload_file(request, upload, session_id="ses_a"))
    assert err.value.status_code == 413
    assert upload.served <= 2 * 1024 * 1024, f"pulled {upload.served} bytes past a 1 MB cap"
