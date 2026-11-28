
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.core.mcp import session_target, tools
from src.models.auto_sleep import SleepVerdict


def _call(monkeypatch, sleeper, family="claude"):
    session = SimpleNamespace(id="ses_a", pty_pid=1, last_activity=None)
    info = SimpleNamespace(session=session, agent_family=family, status_source="registry", startup_gate=None,
                           subagents_state=None, subagents_running=0, background_open=False, background_processes=None)

    async def resolve(*_a, **_k):
        return SimpleNamespace(live=True, info=info)

    monkeypatch.setattr(session_target, "resolve_target", resolve)
    monkeypatch.setattr(tools, "_summary", lambda i: {"id": i.session.id})
    manager = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(auto_sleeper=sleeper)))
    return asyncio.run(tools.session_status(manager, None, {"target": "ses_a"}))


def test_status_returns_the_verdict_or_null(monkeypatch):
    import json

    verdict = SleepVerdict(code="idle_waiting", threshold_minutes=60)
    sleeper = SimpleNamespace(verdict_for=lambda sid: verdict if sid == "ses_a" else None)
    got = json.loads(_call(monkeypatch, sleeper)["content"][0]["text"])
    assert got["sleep_verdict"]["code"] == "idle_waiting" and got["sleep_verdict"]["threshold_minutes"] == 60
    assert json.loads(_call(monkeypatch, None)["content"][0]["text"])["sleep_verdict"] is None
    assert json.loads(_call(monkeypatch, sleeper, family="terminal")["content"][0]["text"])["sleep_verdict"] is None
