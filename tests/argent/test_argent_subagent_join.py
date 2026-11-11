
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from src.core.argent import subagent_join as sj

DECLARE = "mcp__carnivore__argent_story_declare"


def _line(tool_id: str, work_item: str, agent: str = "") -> str:
    record = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tool_id, "name": DECLARE, "input": {"work_item_id": work_item}}]}}
    if agent:
        record["agentId"] = agent
    return json.dumps(record) + "\n"


def _tree(tmp_path: Path) -> Path:
    main = tmp_path / "u1.jsonl"
    main.write_text(_line("toolu_root", "wi_root"))
    subs = tmp_path / "u1" / "subagents"
    (subs / "workflows" / "wf_1").mkdir(parents=True)
    (subs / "agent-aaaa1111.jsonl").write_text(_line("toolu_a", "wi_a", "aaaa1111") * 2)
    (subs / "agent-bbbb2222.jsonl").write_text(_line("toolu_b", "wi_same", "bbbb2222"))
    (subs / "workflows" / "wf_1" / "agent-cccc3333.jsonl").write_text(_line("toolu_c", "wi_same", "cccc3333"))
    return main


def test_join_by_tool_use_id_names_the_agent(tmp_path: Path) -> None:
    main = _tree(tmp_path)
    assert sj.join_once(main, tool_use_id="toolu_a") == sj.JoinResult("aaaa1111", sj.HOW_ID, True)
    assert sj.join_once(main, tool_use_id="toolu_c") == sj.JoinResult("cccc3333", sj.HOW_ID, True)
    assert sj.join_once(main, tool_use_id="toolu_root") == sj.JoinResult("", sj.HOW_ROOT, True)


def test_join_by_name_and_input_and_ambiguity_falls_back_to_root(tmp_path: Path) -> None:
    main = _tree(tmp_path)
    one = sj.join_once(main, tool_name=DECLARE, tool_input={"work_item_id": "wi_a"})
    assert one == sj.JoinResult("aaaa1111", sj.HOW_INPUT, True)
    both = sj.join_once(main, tool_name=DECLARE, tool_input={"work_item_id": "wi_same"})
    assert both == sj.JoinResult("", sj.HOW_FALLBACK_AMBIGUOUS, False)


def test_unflushed_call_retries_then_answers_root_and_late_line_is_found(tmp_path: Path) -> None:
    main = _tree(tmp_path)
    miss = asyncio.run(sj.join(main, tool_use_id="toolu_late", attempts=2, delay=0.01))
    assert miss == sj.JoinResult("", sj.HOW_FALLBACK_NONE, False)
    late = tmp_path / "u1" / "subagents" / "agent-dddd4444.jsonl"

    async def flow() -> sj.JoinResult:
        async def write_later() -> None:
            await asyncio.sleep(0.05)
            late.write_text(_line("toolu_late", "wi_d", "dddd4444"))

        task = asyncio.create_task(write_later())
        got = await sj.join(main, tool_use_id="toolu_late", attempts=10, delay=0.05)
        await task
        return got

    assert asyncio.run(flow()) == sj.JoinResult("dddd4444", sj.HOW_ID, True)


def test_no_transcript_or_no_key_is_root_and_meta_reader() -> None:
    assert asyncio.run(sj.join(None, tool_use_id="x")).sub_agent_id == ""
    assert asyncio.run(sj.join(Path("/nope/u.jsonl"))).how == sj.HOW_FALLBACK_NONE
    assert sj.tool_use_id_from_meta({"_meta": {sj.TOOL_USE_META_KEY: "toolu_1"}}) == "toolu_1"
    assert sj.tool_use_id_from_meta({"_meta": {sj.TOOL_USE_META_KEY: 5}}) == ""
    assert sj.tool_use_id_from_meta(None) == ""
