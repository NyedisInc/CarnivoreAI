
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from src.core import resource_push
from src.core.approvals.inbox import ApprovalsInbox
from src.core.approvals.startup_prompt_provider import (
    SOURCE_STARTUP_PROMPT,
    StartupPromptProvider,
    journal_writer,
)
from src.core.attention.startup_screen import StartupScreen

NOW = datetime(2026, 10, 4, 18, 0, tzinfo=timezone.utc)
SCREEN = StartupScreen("mcp_server", "New MCP server found in this project: probe-echo", NOW, True)


class FakeWatcher:

    def __init__(self) -> None:
        self.rows: dict = {}

    def show(self, session_id: str, screen, *, stale: bool = False, dialog=None) -> None:
        evidence = SimpleNamespace(startup_screen=screen, now=NOW, dialog=dialog, agent_family="claude",
                                   identity=("cloude", "carnivore_planner", 100, 200, None))
        self.rows[session_id] = SimpleNamespace(stale=stale, evidence=evidence)

    def observed_session_ids(self):
        return list(self.rows)

    def observation_for(self, session_id, now=None):
        return self.rows.get(session_id)


class FakeManager:
    async def get_session_info(self, session_id):
        return SimpleNamespace(session=SimpleNamespace(id=session_id), label="planner",
                               tmux_session="carnivore_planner", project_name="Garden Planner")


def test_a_startup_screen_is_pushed_then_cleared(monkeypatch, tmp_path) -> None:
    topics: list = []
    monkeypatch.setattr(resource_push, "notify", topics.append)
    frames: list = []
    watcher = FakeWatcher()
    inbox = ApprovalsInbox(frames.append)
    inbox.register(StartupPromptProvider(lambda: watcher, FakeManager,
                                         on_first_seen=journal_writer(lambda: tmp_path, lambda: watcher)))

    watcher.show("ses_1", SCREEN)
    assert inbox.refresh() is True
    assert frames[-1] == {"type": "approvals", "version": 1, "count": 1}
    assert topics == ["approvals"]
    items = asyncio.run(inbox.list_items())
    assert len(items) == 1
    item = items[0]
    assert item["source"] == SOURCE_STARTUP_PROMPT and item["kind"] == "mcp_server"
    assert item["session_name"] == "planner" and item["rows"] == [] and item["options"] == []
    assert "probe-echo" in item["body"]
    log = (tmp_path / "session-journal" / "journal.log").read_text(encoding="utf-8")
    assert "startup_prompt_seen" in log and "carnivore_planner" in log and "probe-echo" in log
    assert log.count("startup_prompt_seen") == 1
    assert inbox.refresh() is False

    watcher.show("ses_1", SCREEN, stale=True)
    assert inbox.refresh() is True
    assert frames[-1] == {"type": "approvals", "version": 2, "count": 0}
    assert topics == ["approvals", "approvals"]
    assert asyncio.run(inbox.list_items()) == []


def test_an_extracted_dialog_wins_and_a_held_fallback_is_not_shown(monkeypatch) -> None:
    monkeypatch.setattr(resource_push, "notify", lambda topic: None)
    watcher = FakeWatcher()
    provider = StartupPromptProvider(lambda: watcher, FakeManager)
    watcher.show("ses_1", SCREEN, dialog=object())
    watcher.show("ses_2", StartupScreen("unrecognized", "x", NOW, False))
    watcher.show("remote:peer-a:x", SCREEN)
    assert provider.signature() == frozenset()
