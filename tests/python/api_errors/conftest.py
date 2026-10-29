
from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any, Dict, Optional, Tuple

import httpx
import pytest
import structlog

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_h3_wd_"))
os.environ.setdefault("TOTP_SECRET", "h3secretnotreal")
os.environ.setdefault("JWT_SECRET", "h3jwtnotreal")

LEAK = "/Users/secret-owner/private/tmux-socket-xyz"


class Driver:

    def call(self, method: str, path: str, manager: Any, json: Optional[Dict[str, Any]] = None
             ) -> Tuple[httpx.Response, list]:
        from src.api.auth import require_auth
        from src.main import app

        previous = getattr(app.state, "session_manager", None)
        app.state.session_manager = manager
        app.dependency_overrides[require_auth] = lambda: True

        async def _drive() -> httpx.Response:
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://localhost/api/v1") as client:
                return await client.request(method, path, json=json)

        try:
            with structlog.testing.capture_logs() as events:
                response = asyncio.run(_drive())
        finally:
            app.dependency_overrides.pop(require_auth, None)
            app.state.session_manager = previous
        return response, events


@pytest.fixture()
def driver() -> Driver:
    return Driver()


def assert_fixed(response, status: int, code: str, events: list, *, text: str = LEAK) -> dict:
    assert response.status_code == status, response.text
    assert text not in response.text
    detail = response.json()["detail"]
    assert detail["code"] == code
    assert detail["detail"] and text not in detail["detail"]
    failures = [e for e in events if e.get("event") == "api_request_failed" and e.get("code") == code]
    assert failures and text in str(failures[0]["error"])
    return detail
