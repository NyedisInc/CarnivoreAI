
from __future__ import annotations

# ruff: noqa: F811 - the

import asyncio
import json
from contextlib import closing
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.core.db import connect, db_path_for
from src.core.swarm import owner_message, reply_mirror, store, stream, watch
from tests.python.swarm.test_swarm_reply_mirror import EPOCH, FINAL, _agent_texts, _assistant, _record, world  # noqa: F401

TOOL_OUTPUT = "TOOL OUTPUT the owner must never see"


def _reading(state: str, *, wrote: datetime, turn_end=None, reason: str = "busy"):
    return SimpleNamespace(verdict=SimpleNamespace(state=state, reason=reason),
                           evidence=SimpleNamespace(dialog=None, identity=("cloude", "cloude_a", EPOCH, 1, "conv-1"),
                                                    transcript=SimpleNamespace(turn_end_at=turn_end, newest_assistant_at=wrote)))


async def _pass(reading) -> None:
    watch.on_observation(SimpleNamespace(key=f"cloude_a@{EPOCH}"), reading)
    for _ in range(200):
        await asyncio.sleep(0.01)
        if not [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]:
            return


def _append(world, *records) -> None:
    with world.transcript.open("a") as out:
        out.write("".join(json.dumps(r) + "\n" for r in records))


def _tool_step(msg_id: str, text: str, tool_id: str):
    return [*_assistant(msg_id, "tool_use", {"type": "thinking", "thinking": "hidden plan"}, {"type": "text", "text": text},
                        {"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": "echo hi"}}),
            _record("user", promptId="p-1", message={"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tool_id, "content": TOOL_OUTPUT}]})]


def _agent_entries(world):
    with closing(connect(db_path_for(world.transcript.parent))) as conn:
        agent = store.get_agent(conn, world.loki["id"])
    return [e for e in asyncio.run(stream.page(agent))["entries"] if e["kind"] == "agent"]


def _start(world):
    out = asyncio.run(owner_message.post_owner_message(world.app_state, world.loki["id"], "swap the models"))
    assert out.outcome == "delivered"
    reply_mirror.reset()
    reply_mirror.note_owner_delivery(world.loki["id"])
    world.transcript.write_text(json.dumps(_record("user", promptId="p-1", uuid="u-1",
                                                   message={"role": "user", "content": world.pasted[0]})) + "\n")
    watch.register(world.app_state, "cloude_a", world.loki["id"], EPOCH)
    watch._unsettled.clear()


def test_one_draft_grows_then_the_final_answer_replaces_it(world):
    _start(world)
    t0 = datetime.now(timezone.utc)
    _append(world, *_tool_step("m1", "Looking at the model table.", "t1"))
    asyncio.run(_pass(_reading("busy", wrote=t0)))
    first = _agent_entries(world)
    assert [(e["text"], e["draft"]) for e in first] == [("Looking at the model table.", "writing")]

    _append(world, *_tool_step("m2", "Found it: two rows to swap.", "t2"))
    asyncio.run(_pass(_reading("busy", wrote=t0 + timedelta(seconds=2))))
    grown = _agent_entries(world)
    assert [e["id"] for e in grown] == [first[0]["id"]]
    assert grown[0]["text"] == "Looking at the model table.\n\nFound it: two rows to swap." and grown[0]["draft"] == "writing"

    _append(world, *_assistant("m3", "end_turn", {"type": "text", "text": FINAL}))
    ended = t0 + timedelta(seconds=4)
    asyncio.run(_pass(_reading("idle", wrote=ended, turn_end=ended, reason="idle")))
    final = _agent_entries(world)
    assert [(e["text"], e.get("draft")) for e in final] == [(FINAL, None)]
    assert _agent_texts(world) == [FINAL]
    seen = json.dumps([first, grown, final])
    assert TOOL_OUTPUT not in seen and "hidden plan" not in seen and "echo hi" not in seen


def test_a_body_that_dies_mid_turn_leaves_its_draft_marked_stopped(world):
    _start(world)
    t0 = datetime.now(timezone.utc)
    _append(world, *_tool_step("m1", "Halfway through the swap.", "t1"))
    asyncio.run(_pass(_reading("busy", wrote=t0)))
    assert [e["draft"] for e in _agent_entries(world)] == ["writing"]
    asyncio.run(_pass(_reading("unknown", wrote=t0, reason="pane_dead")))
    after = _agent_entries(world)
    assert [(e["text"], e["draft"]) for e in after] == [("Halfway through the swap.", "stopped")]
    assert _agent_texts(world) == []
