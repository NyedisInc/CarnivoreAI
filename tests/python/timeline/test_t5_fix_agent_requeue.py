
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, List

import pytest

from src.core.timeline import agent_tail, subscribe
from tests.python.timeline.exposure_helpers import CONV, append, turn, user


def _conv(tmp_path: Path, number: int) -> Path:
    main = tmp_path / f"p{number}" / f"{CONV[:-1]}{number}.jsonl"
    append(main, turn(0, "a"))
    append(main.with_suffix("") / "subagents" / "agent-a1.jsonl", [user(1, "x")])
    return main


def test_n3_a_drain_stops_between_conversations_once_cleared(tmp_path: Path, switch, monkeypatch: pytest.MonkeyPatch) -> None:
    tails = agent_tail.AgentTails()
    mains = [_conv(tmp_path, number) for number in (1, 2)]
    polled: List[str] = []

    def poll(main_real: str, conv: str, family: str = "claude") -> int:
        polled.append(conv)
        tails.clear()
        return 0

    monkeypatch.setattr(tails, "poll", poll)
    for number, main in enumerate(mains):
        tails.enqueue(str(main), f"c{number}")
    tails.drain()
    assert polled == ["c0"], f"a cleared drain went on to poll {polled}"


def test_n3_a_poll_of_a_tail_clear_dropped_does_nothing(tmp_path: Path, frames, switch, monkeypatch: pytest.MonkeyPatch) -> None:
    sent, clock = frames
    tails = agent_tail.AgentTails()
    main = _conv(tmp_path, 1)
    tails.poll(str(main), "c1")
    append(main.with_suffix("") / "subagents" / "agent-a1.jsonl", [user(2, "y")])
    real = tails._tail_for

    def racing(main_real: str) -> Any:
        tail = real(main_real)
        tails.clear()
        return tail

    monkeypatch.setattr(tails, "_tail_for", racing)
    assert tails.poll(str(main), "c1") == 0
    clock.advance(2.0)
    assert sent == [], "a dropped tail still moved a frame"


def test_n4_a_read_the_page_budget_cut_is_queued_again(tmp_path: Path, frames, switch, monkeypatch: pytest.MonkeyPatch) -> None:
    tails = agent_tail.AgentTails()
    main = _conv(tmp_path, 1)
    agent = main.with_suffix("") / "subagents" / "agent-a1.jsonl"
    tails.poll(str(main), "c1")
    got: List[subscribe.TimelineBatch] = []
    subscribe.subscribe(None, got.append)
    monkeypatch.setattr(agent_tail, "MAX_PAGES_PER_POLL", 1)
    append(agent, [user(number, f"step {number}") for number in range(2, 1300)])
    real = str(main.resolve())
    assert tails.poll(real, "c1") == 1 and tails._pending == {real: "c1"}  # noqa: SLF001
    for _ in range(10):
        tails.drain()
    assert sum(len(batch.events) for batch in got) == 1298 and not tails._pending  # noqa: SLF001


def test_a_page_that_made_no_progress_is_done_so_an_unfinished_long_line_does_not_spin(tmp_path: Path, switch, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = tmp_path / "agent-a1.jsonl"
    first = json.dumps({"type": "user", "uuid": "u1", "parentUuid": None, "message": {"role": "user", "content": "hi"}}) + "\n"
    agent.write_text(first + '{"type":"user","message":{"content":"' + "x" * 200_000)
    pos = agent_tail._AgentPos(os.stat(agent).st_ino, -1, len(first), None)
    reads: List[int] = []
    real_read = agent_tail.reading.read_from

    def counted(*args: Any, **kwargs: Any) -> Any:
        reads.append(1)
        return real_read(*args, **kwargs)

    monkeypatch.setattr(subscribe, "listening", lambda: True)
    monkeypatch.setattr(agent_tail.reading, "read_from", counted)
    _events, done = agent_tail.AgentTails._advance(pos, CONV, "a1", str(agent), "claude", os.stat(agent))
    assert done is True and pos.end == len(first), "a read that moved nothing must count as done"
    assert len(reads) == 1, f"the page loop went on after a page that made no progress ({len(reads)} reads)"


def test_the_switch_fixture_stops_the_worker_of_a_private_agent_tails(switch) -> None:
    tails = agent_tail.AgentTails()
    tails.enqueue("/x/1", "c0")
    assert tails.worker_enabled is False and tails._worker is None
