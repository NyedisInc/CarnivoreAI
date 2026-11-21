
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import src
from src.core.timeline import agent_tail
from tests.python.timeline.exposure_helpers import CONV, Client, append, step, turn, user
from tests.python.timeline.test_t5_fix_hotpath import _agent



def test_finding4_a_dropped_frame_naming_only_an_agent_file_is_detected_by_seq_and_healed_by_state(api, frames, switch) -> None:
    client, main = api
    sent, clock = frames
    real_main, agent = str(main.resolve()), _agent(main)
    append(main, turn(0, "a"))
    append(agent, [user(1, "agent prompt")])
    agent_tail.TAILS.poll(real_main, CONV)
    paths = lambda key: real_main if key == "main" else str(agent.resolve())  # noqa: E731
    chat, last_seq = Client(paths), 0

    def heal() -> int:
        answer = client.get("/api/v1/sessions/ses_1/timeline/state").json()
        for key, (offset, _serial) in answer["files"].items():
            held = chat.pos.get(key)
            if held is None or offset > held.offset:
                chat.catch_up(key)
        return answer["seq"]

    def receive(frame: Dict[str, Any]) -> None:
        nonlocal last_seq
        if frame["seq"] != last_seq + 1:
            heal()
        else:
            chat.on_frame(frame)
        last_seq = frame["seq"]

    last_seq = heal()
    append(main, turn(10, "b"))
    step(main)
    receive(sent[0])
    clock.advance(1.5)
    append(agent, [user(2, "agent step")])
    agent_tail.TAILS.poll(real_main, CONV)
    assert set(sent[1]["moved"]) == {"a1"}
    clock.advance(1.5)
    append(main, turn(20, "c"))
    step(main)
    assert sent[2]["seq"] == sent[0]["seq"] + 2
    receive(sent[2])
    whole = Client(paths)
    whole.catch_up("main")
    whole.catch_up("a1")
    assert sorted(chat.seen) == sorted(whole.seen) and any(":a1:" in event for event in chat.seen)


def test_finding4_the_state_names_every_file_and_the_last_seq(api, frames, switch) -> None:
    client, main = api
    sent, _clock = frames
    append(main, turn(0, "a"))
    append(_agent(main, "a1"), [user(1, "x")])
    append(_agent(main, "a2"), [user(2, "y"), user(3, "z")])
    step(main)
    answer = client.get("/api/v1/sessions/ses_1/timeline/state").json()
    assert set(answer["files"]) == {"main", "a1", "a2"} and answer["seq"] == sent[-1]["seq"]
    assert answer["files"]["a2"][0] == _agent(main, "a2").stat().st_size and answer["files"]["a2"][1]


def test_lowd_named_constants_replace_the_magic_values() -> None:
    core = Path(src.__file__).parent / "core"
    for relative, literal in [("timeline/index_read.py", "1 << 62"), ("mcp/session_events_tools.py", "1 << 62"),
                              ("timeline/agent_tail.py", '"file_rewritten"'), ("timeline/resolve.py", '"claude"')]:
        assert literal not in (core / relative).read_text(), f"{relative} still carries {literal}"
