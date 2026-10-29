
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mcp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mcp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from types import SimpleNamespace  # noqa: E402

from src.api import app_alerts_routes, provider_ledger_routes, session_git_routes  # noqa: E402
from src.core.mcp import read_tools  # noqa: E402
from src.models.session_git import GitFile, SessionGitStatus  # noqa: E402
from src.core.mcp import tools  # noqa: E402
from src.core.mcp.caller import AgentCaller  # noqa: E402
from src.core.provider_ledger import pace  # noqa: E402
from src.models.provider_ledger import AccountUsage, LedgerSnapshot, LedgerTotal, LoopStatus, UsageWindow  # noqa: E402

NAMES = ("usage_ledger", "alerts_list", "session_git_status")
SECRET = "ghp_" + "aB3xY9" * 6


def _caller() -> AgentCaller:
    return AgentCaller("ses_test", "cloude_test", "ses_test")


async def _run(name: str, args: dict | None = None):
    res = await tools.call_tool(None, _caller(), name, args or {})
    assert "isError" not in res, res
    return res, json.loads(res["content"][0]["text"])


def _assert_no_token_keys(value) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            assert "token" not in k.lower(), k
            _assert_no_token_keys(v)
    elif isinstance(value, list):
        for v in value:
            _assert_no_token_keys(v)


def test_tools_are_listed():
    listed = {t["name"] for t in tools.tool_definitions()}
    assert set(NAMES) <= listed
    assert all(tools.has_tool(n) for n in NAMES)


@pytest.mark.asyncio
async def test_usage_ledger_shape_pace_and_no_tokens(monkeypatch):
    reset = datetime.now(timezone.utc) + timedelta(hours=1)
    snap = LedgerSnapshot(
        accounts=[AccountUsage(id="c1", name="main", provider="claude", credential_state="ok",
                               windows=[UsageWindow(kind="five_hour", label="5h", used_pct=90.0, resets_at=reset)])],
        total=LedgerTotal(accounts=1), loop=LoopStatus(alive=True),
    )

    async def fake():
        return snap

    monkeypatch.setattr(provider_ledger_routes, "get_provider_ledger", fake)
    _, body = await _run("usage_ledger")
    win = body["accounts"][0]["windows"][0]
    assert set(win) == {"kind", "label", "used_pct", "elapsed_pct", "pace", "resets_at"}
    assert 79 < win["elapsed_pct"] < 81 and win["pace"] == "ahead"
    _assert_no_token_keys(body)


def test_pace_state_matches_the_js_rules():
    assert pace.pace_state(80, 40) == "over"
    assert pace.pace_state(3, 1) == "on"
    assert pace.pace_state(None, 40) is None


@pytest.mark.asyncio
async def test_route_answers_pass_through_redacted_and_token_free(monkeypatch):
    async def alerts(state, limit):
        assert state == "active" and limit <= 50
        return {"alerts": [{"title": f"leaked {SECRET}"}], "counts": {"active": 1}}

    monkeypatch.setattr(app_alerts_routes, "list_alerts", alerts)

    res, body = await _run("alerts_list")
    assert body["counts"] == {"active": 1} and SECRET not in res["content"][0]["text"]


@pytest.mark.asyncio
async def test_session_git_status_resolves_the_target_calls_the_route_and_redacts(monkeypatch):
    info = SimpleNamespace(session=SimpleNamespace(id="ses_1"), tmux_session="cloude_a", host_key="local")
    seen = []

    async def infos(manager):
        return [info]

    async def route(request, session_id):
        seen.append(session_id)
        return SessionGitStatus(state="ok", branch="main", files=[GitFile(path=f"leak_{SECRET}.txt", index=" ", worktree="M", kind="modified")])

    monkeypatch.setattr("src.core.mcp.common._all_infos", infos)
    monkeypatch.setattr(session_git_routes, "get_session_git_status", route)
    monkeypatch.setattr("src.core.mcp.write_tools._request", lambda manager: SimpleNamespace(app=None))

    missing = await tools.call_tool(None, _caller(), "session_git_status", {})
    assert missing["isError"] is True
    res, body = await _run("session_git_status", {"target": "cloude_a"})
    assert seen == ["ses_1"] and body["state"] == "ok" and body["branch"] == "main"
    assert SECRET not in res["content"][0]["text"]
