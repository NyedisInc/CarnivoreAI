from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import peer_route_guard, session_input_routes


def _request(session):
    registry = SimpleNamespace(get_session=lambda sid: session if sid == "known" else None,
                               current_session=lambda: SimpleNamespace(id="ses_active", working_dir="/w"))
    app = SimpleNamespace(state=SimpleNamespace(session_manager=SimpleNamespace(has_active_session=lambda: True),
                                                services=SimpleNamespace(registry=registry)))
    return SimpleNamespace(app=app, state=SimpleNamespace(peer_grant=object()))


@pytest.mark.parametrize("session_id,status", [(None, 400), ("", 400), ("nope", 404)])
def test_a_peer_upload_without_a_known_session_is_refused_not_sent_to_the_active_one(session_id, status) -> None:
    with pytest.raises(HTTPException) as caught:
        asyncio.run(session_input_routes.upload_file(_request(None), SimpleNamespace(), session_id))
    assert caught.value.status_code == status


def test_a_forwarded_upload_is_read_only_up_to_the_cap(monkeypatch) -> None:
    cfg = SimpleNamespace(uploads=SimpleNamespace(max_size_mb=1, max_file_size_mb=1))
    monkeypatch.setattr(type(peer_route_guard.settings), "load_auth_config", lambda self: cfg)
    asked = []

    class Part:
        filename = "big.bin"

        async def read(self, size=-1):
            asked.append(size)
            return b"x" * (3 * 1024 * 1024 if size < 0 else size)

    class Conn:
        headers = {}

        async def form(self):
            return {"file": Part()}

    with pytest.raises(HTTPException) as caught:
        asyncio.run(peer_route_guard._raw_upload(Conn()))
    assert caught.value.status_code == 413
    assert asked and asked[0] == 2 * 1024 * 1024 + 1
