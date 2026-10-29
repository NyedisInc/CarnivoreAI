
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from src.core.mcp import pending, tools
from src.core.mcp.caller import AgentCaller
from src.core.ui_preferences_store import UiPreferencesStore


def grid(*slots: str) -> dict:
    return {
        "v": 6,
        "rows": [{"id": "r1", "kind": "px", "size": 120, "slots": [{"id": s, "fr": 1 / len(slots)} for s in slots]}],
        "hidden": [],
        "heroCollapsed": False,
        "collapsed": [],
    }


@pytest.fixture
def manager(tmp_path: Path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"agents": {"a": 1}}))
    monkeypatch.setenv("CLOUDE_STATE_DIR", str(tmp_path))
    app = FastAPI()
    app.state.ui_preferences_store = UiPreferencesStore(lambda: path)
    app.state.connection_manager = None
    home = {"v": 2, "boards": [{"id": "home", "name": "ops", "layout": grid("stat-running", "projects")}]}
    assert app.state.ui_preferences_store.update({"home_layout": home}).status == "committed"
    return SimpleNamespace(app=app, gate_waited=True)


CALLER = AgentCaller("ses_1", "cloude_a", "ses_1")


def call(manager, name, args, caller=CALLER):
    result = asyncio.run(tools.call_tool(manager, caller, name, args))
    return result, json.loads(result["content"][0]["text"]) if not result.get("isError") else result["content"][0]["text"]


def boards(manager) -> list:
    return manager.app.state.ui_preferences_store.read()["values"]["home_layout"]["boards"]


def test_export_then_import_waits_for_the_owner_then_adds_the_board(manager):
    _, document = call(manager, "board_export", {"board_id": "home"})
    assert document["format"] == "carnivore-board"
    _, preview = call(manager, "board_import", {"document": document, "dry_run": True})
    assert preview["preview"]["ok"] is True and len(boards(manager)) == 1
    _, answer = call(manager, "board_import", {"document": document})
    assert answer["status"] == "pending" and len(boards(manager)) == 1
    item = asyncio.run(pending.get_store().approve(answer["id"]))
    assert json.loads(item.result["content"][0]["text"])["status"] == "imported"
    assert [board["name"] for board in boards(manager)] == ["ops", "ops"]


def test_a_refused_file_lists_every_reason_and_never_reaches_the_inbox(manager):
    _, document = call(manager, "board_export", {})
    document["board"]["layout"] = grid("no-such-widget", "also-missing")
    result, text = call(manager, "board_import", {"document": document})
    assert result["isError"] and "no-such-widget" in text
    assert len(boards(manager)) == 1


def test_a_read_token_sees_the_export_and_not_the_import():
    read_only = AgentCaller("", "", "", scope="read", token_name="reader")
    names = {tool["name"] for tool in tools.tool_definitions(read_only)}
    assert "board_export" in names and "board_import" not in names
    assert not tools.allowed(read_only, "board_import")
