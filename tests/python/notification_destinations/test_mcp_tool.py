
from __future__ import annotations

import asyncio
import json
import os
import tempfile

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mcp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mcp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core.mcp import tools  # noqa: E402
from src.core.mcp.caller import AgentCaller  # noqa: E402
from src.core.notifications import routing_view  # noqa: E402
from src.core.notifications.destinations import service as service_mod  # noqa: E402

SENTINEL = "SENTINEL-xyzzy-9f3a"


def test_tool_listed():
    assert "notification_destinations_list" in {t["name"] for t in tools.tool_definitions()}


@pytest.mark.asyncio
async def test_lists_destinations_without_secrets(service, monkeypatch):
    monkeypatch.setattr(service_mod, "_current", service)
    made = await service.destinations.create(
        "slack", "team", {}, {"url": f"https://hooks.slack.com/services/T/B/{SENTINEL}"})
    dest = made.destination["id"]
    monkeypatch.setattr(routing_view, "_status_provider",
                        lambda: {dest: routing_view.DestinationStatus(last_ok_ts=5.0)})
    res = await tools.call_tool(None, AgentCaller(session_id="ses_test", tmux_name="carnivore_test", current_session_id="ses_test"), "notification_destinations_list", {})
    assert "isError" not in res, res
    text = res["content"][0]["text"]
    body = json.loads(text)
    row = body["destinations"][0]
    assert (row["kind"], row["name"], row["enabled"], row["scope"], row["status"]) == ("slack", "team", True, "global", "ok")
    assert "session.finished" in row["ticked_types"] and "alert.notifications" not in row["ticked_types"]
    assert SENTINEL not in text and "hooks.slack.com" not in text and set(row) == {
        "kind", "name", "enabled", "scope", "status", "ticked_types"}


@pytest.fixture(autouse=True)
def _no_status_provider():
    yield
    routing_view.uninstall_routing()
