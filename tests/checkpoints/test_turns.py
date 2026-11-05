
from __future__ import annotations

import asyncio

from src.api import checkpoint_capture
from src.core.checkpoints.turns import newest_turn


def _prompt(uid: str, text: str = "fix it") -> dict:
    return {"type": "user", "uuid": uid, "message": {"role": "user", "content": text}}


def _assistant(tool: bool) -> dict:
    block = {"type": "tool_use", "id": "t", "name": "Bash", "input": {}} if tool else {"type": "text", "text": "ok"}
    return {"type": "assistant", "uuid": "a", "message": {"role": "assistant", "content": [block]}}


def test_newest_turn_reads_the_last_prompt_and_its_tools() -> None:
    assert newest_turn([_prompt("p1"), _assistant(True), _prompt("p2"), _assistant(False)]).prompt_uuid == "p2"
    assert newest_turn([_prompt("p1"), _assistant(False)]).used_tools is False
    assert newest_turn([_prompt("p1"), _assistant(True)]).used_tools is True
    tool_result = {"type": "user", "uuid": "r", "message": {"content": [{"type": "tool_result", "tool_use_id": "t"}]}}
    assert newest_turn([_prompt("p1"), _assistant(True), tool_result]).prompt_uuid == "p1"
    assert newest_turn([_assistant(True)]) is None


def test_a_gone_or_remote_session_captures_nothing() -> None:
    class Manager:
        async def get_session_info(self, _sid):
            return None

    assert asyncio.run(checkpoint_capture.on_turn_end(Manager(), "ses_gone")) == "gone"
    assert asyncio.run(checkpoint_capture.on_turn_end(Manager(), "remote:peer-x:ses_1")) == "remote"
