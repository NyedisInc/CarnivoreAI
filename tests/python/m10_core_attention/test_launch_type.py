
from __future__ import annotations

from src.core.attention.turn_counts import KIND_AGENT, Launch, async_launch


def test_agent_launch_is_a_launch_tuple() -> None:
    record = {"toolUseResult": {"isAsync": True, "agentId": "a1"},
              "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_1"}]}}
    launch = async_launch(record)
    assert launch == Launch("toolu_1", KIND_AGENT, "a1", "toolu_1")
    assert launch.key == "toolu_1" and launch.kind == KIND_AGENT


def test_launch_without_ids_is_not_counted() -> None:
    assert async_launch({"toolUseResult": {"isAsync": True}}) is None
