
from __future__ import annotations

import os
import tempfile
from typing import Any

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mcp_dc_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mcp_dc_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

import pytest  # noqa: E402
from starlette.requests import Request  # noqa: E402
from structlog.testing import capture_logs  # noqa: E402

from src.api import mcp_routes  # noqa: E402
from src.core.log_level import live as live_log_level  # noqa: E402

_BODY_SECRET = "ghp_" + "aB3xY9" * 6


def _request_that_hangs_up(first_chunk: bytes) -> Request:
    messages = [
        {"type": "http.request", "body": first_chunk, "more_body": True},
        {"type": "http.disconnect"},
    ]

    async def receive() -> dict[str, Any]:
        return messages.pop(0)

    scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": [(b"user-agent", b"claude-code")], "client": ("10.0.0.9", 1)}
    return Request(scope, receive)


@pytest.mark.asyncio
async def test_a_client_that_hangs_up_mid_body_raises_nothing_and_logs_no_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_log_level, "_current", live_log_level.number_for("debug"))
    handler = mcp_routes.mcp_post.__wrapped__
    with capture_logs() as logs:
        response = await handler(_request_that_hangs_up(_BODY_SECRET.encode()), caller=None)
    assert response.status_code == mcp_routes.CLIENT_CLOSED_STATUS
    assert not [e for e in logs if e["log_level"] in ("error", "critical")]
    disconnects = [e for e in logs if e["event"] == "mcp_client_disconnected"]
    assert len(disconnects) == 1 and disconnects[0]["log_level"] == "debug"
    assert disconnects[0]["route"] == "/mcp"
    assert _BODY_SECRET not in repr(logs)


@pytest.mark.asyncio
async def test_the_real_app_answers_499_to_a_mid_body_hang_up_without_raising(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from src.api.agent_auth import require_agent
    from src.core.mcp.caller import AgentCaller
    from src.main import app

    monkeypatch.setattr(live_log_level, "_current", live_log_level.number_for("debug"))
    monkeypatch.setitem(app.dependency_overrides, require_agent, lambda: AgentCaller.__new__(AgentCaller))
    monkeypatch.setitem(app.dependency_overrides, mcp_routes.mcp_enabled, lambda: None)
    messages = [
        {"type": "http.request", "body": _BODY_SECRET.encode(), "more_body": True},
        {"type": "http.disconnect"},
    ]
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return messages.pop(0)

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http", "http_version": "1.1", "method": "POST", "path": "/mcp", "raw_path": b"/mcp", "query_string": b"",
        "headers": [(b"host", b"testserver"), (b"content-type", b"application/json")], "client": ("10.0.0.9", 1),
        "server": ("testserver", 80), "scheme": "http", "root_path": "", "app": app,
    }
    with capture_logs() as logs, caplog.at_level("DEBUG"):
        await app(scope, receive, send)
    start = [m for m in sent if m["type"] == "http.response.start"]
    assert start and start[0]["status"] == mcp_routes.CLIENT_CLOSED_STATUS
    assert not [e for e in logs if e["log_level"] in ("error", "critical")]
    assert not [r for r in caplog.records if r.levelname in ("ERROR", "CRITICAL")]
    assert _BODY_SECRET not in repr(logs) + caplog.text
