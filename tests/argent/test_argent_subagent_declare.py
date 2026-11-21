
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.core.argent import declare, declare_instructions, subagent_join
from src.core.argent.lifecycle import PORT_NAME
from src.core.mcp import argent_tools, instructions, protocol, tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError
from src.core.session_token_usage import claude_reader
from src.core.session_transcript_presence import CONVERSATION_PRESENT
from src.plugins.sdk import ports

NAME = "mcp__carnivore__argent_story_declare"
PANE = AgentCaller(session_id="ses_1", tmux_name="carnivore_a", current_session_id="ses_1")
HANDLER = argent_tools.WRITE_TOOLS["argent_story_declare"][3]


def _use(tool_id: str, item: str, prompt_first: str = "") -> str:
    blocks: List[Dict[str, Any]] = [{"type": "tool_use", "id": tool_id, "name": NAME, "input": {"work_item_id": item}}]
    return json.dumps({"type": "assistant", "message": {"content": blocks}, "note": prompt_first}) + "\n"


def _transcripts(tmp_path: Path) -> Path:
    main = tmp_path / "u1.jsonl"
    main.write_text(_use("toolu_root", "wi_story"))
    subs = tmp_path / "u1" / "subagents"
    subs.mkdir(parents=True)
    prompt = json.dumps({"type": "user", "message": {"content": "argent-story: wi_story\nreview the diff"}}) + "\n"
    (subs / "agent-aaaa1111.jsonl").write_text(prompt + _use("toolu_sub", "wi_story"))
    return main


class Manager:
    def __init__(self, family: str = "claude") -> None:
        self.family = family

    async def get_session_info(self, session_id: str) -> Any:
        return SimpleNamespace(agent_family=self.family, tmux_session="carnivore_a", session=SimpleNamespace(working_dir="/w"))

    def claude_uuid_for_tmux_name(self, name: str) -> str:
        return "u1"


@pytest.fixture
def declared(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> List[tuple]:
    main = _transcripts(tmp_path)
    monkeypatch.setattr(claude_reader, "locate_transcript", lambda uuid, working_dir=None, projects_dir=None: claude_reader.TranscriptLocation(CONVERSATION_PRESENT, main))
    calls: List[tuple] = []

    async def fake_declare(tmux: str, item: str, source: str, sub: str = "") -> Dict[str, Any]:
        calls.append((tmux, item, source, sub))
        return {"session_id": "argent-1", "sub_agent_id": sub, "work_item_id": item, "ts": "t", "reason": source, "changed": True}

    monkeypatch.setattr(declare, "declare", fake_declare)
    return calls


def _call(caller: AgentCaller, args: dict, tool_use_id: str, manager: Any = None) -> Any:
    async def run() -> Any:
        token = subagent_join.CURRENT_TOOL_USE_ID.set(tool_use_id)
        try:
            return await HANDLER(manager or Manager(), caller, args)
        finally:
            subagent_join.CURRENT_TOOL_USE_ID.reset(token)

    return asyncio.run(run())


def test_a_sub_agent_call_is_filed_under_that_sub_agent_and_recorded_mcp_self(declared: List[tuple]) -> None:
    out = _call(PANE, {"work_item_id": "wi_story"}, "toolu_sub")
    assert declared == [("carnivore_a", "wi_story", "mcp-self", "aaaa1111")]
    assert json.loads(out["content"][0]["text"])["joined"] == subagent_join.HOW_ID
    declared.clear()
    _call(PANE, {"work_item_id": "wi_story"}, "toolu_root")
    assert declared == [("carnivore_a", "wi_story", "mcp-self", "")]
    declared.clear()
    _call(PANE, {"work_item_id": "wi_story"}, "")
    assert declared == [("carnivore_a", "wi_story", "mcp-self", "")]


def test_codex_stays_session_level(declared: List[tuple]) -> None:
    _call(PANE, {"work_item_id": "wi_story"}, "toolu_sub", Manager("codex"))
    assert declared[0][3] == ""


@pytest.mark.parametrize("caller,args", [
    (AgentCaller("mcp-token:1", "mcp-token:1", "mcp-token:1", token_name="ext", scope="write"), {"work_item_id": "wi"}),
    (AgentCaller("ses_1", "carnivore_a", "ses_1", proxied_agent_id=7), {"work_item_id": "wi"}),
    (PANE, {"work_item_id": "wi", "target": "carnivore_b"}),
    (PANE, {"work_item_id": "wi", "budget": 1}),
    (PANE, {}),
])
def test_only_the_calling_pane_declares_and_nothing_else_is_accepted(declared: List[tuple], caller: AgentCaller, args: dict) -> None:
    with pytest.raises(ToolError):
        _call(caller, args, "toolu_sub")
    assert declared == []


def test_feature_off_is_inert() -> None:
    ports.unregister(PORT_NAME)
    with pytest.raises(ToolError, match="feature_off"):
        _call(PANE, {"work_item_id": "wi"}, "toolu_sub")


def test_protocol_passes_the_tool_use_id_through_and_clears_it(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: List[str] = []

    async def spy(manager: Any, caller: Any, name: str, args: Any) -> dict:
        seen.append(subagent_join.CURRENT_TOOL_USE_ID.get())
        return {"content": []}

    monkeypatch.setattr(tools, "call_tool", spy)
    monkeypatch.setattr(tools, "has_tool", lambda name: True)

    def rpc(meta: Any) -> dict:
        params: Dict[str, Any] = {"name": "argent_story_declare", "arguments": {}}
        if meta is not None:
            params["_meta"] = meta
        return {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}

    asyncio.run(protocol.handle_message(rpc({"claudecode/toolUseId": "toolu_9"}), None, PANE))
    asyncio.run(protocol.handle_message(rpc(None), None, PANE))
    assert seen == ["toolu_9", ""]
    assert subagent_join.CURRENT_TOOL_USE_ID.get() == ""


def test_instruction_is_in_the_guide_only_while_the_feature_is_on() -> None:
    ports.unregister(PORT_NAME)
    assert "argent_story_declare" not in instructions.guide(PANE)
    ports.register(PORT_NAME, {"on": True})
    try:
        text = instructions.guide(PANE)
        assert "argent-story: <item id>" in text and "argent_story_declare" in text
        assert len(text) <= instructions.MAX_CHARS
        assert len(instructions.guide(PANE, channel=True)) <= instructions.MAX_CHARS
        assert declare_instructions.text(10) == ""
        assert "argent-story: <item id>" in argent_tools.WRITE_TOOLS["argent_story_declare"][0]
        read_only = AgentCaller("mcp-token:1", "mcp-token:1", "mcp-token:1", token_name="ro", scope="read")
        assert "argent_story_declare" not in instructions.guide(read_only)
    finally:
        ports.unregister(PORT_NAME)
    assert declare_instructions.text(5000) == ""
