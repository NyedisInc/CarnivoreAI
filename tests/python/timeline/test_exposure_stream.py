
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from src.core.timeline import agent_tail, ctx_cache, cursor as cursors, hot, reading, subscribe
from src.core.timeline.model import Kind
from tests.python.timeline.exposure_helpers import (
    CONV, Client, append, step, turn, user,
)


def _main(tmp_path: Path) -> Path:
    return tmp_path / "proj" / f"{CONV}.jsonl"


def test_two_clients_one_drops_a_frame_and_one_catch_up_read_makes_their_lists_identical(tmp_path: Path, frames, switch) -> None:
    sent, clock = frames
    main = _main(tmp_path)
    paths = lambda key: str(main)  # noqa: E731
    a, b = Client(paths), Client(paths)
    for index in range(4):
        append(main, turn(10 * index, str(index)))
        step(main)
        clock.advance(1.5)
    assert len(sent) == 4 and all(f["session_uuid"] and f["moved"]["main"][0] > 0 for f in sent)
    assert all(set(f) <= {"type", "session_uuid", "epoch", "seq", "conv", "moved", "state", "reset"} for f in sent)
    for index, frame in enumerate(sent):
        a.on_frame(frame)
        if index != 1:
            b.on_frame(frame)
    ctx_cache.clear()
    b.on_frame(sent[-1])
    whole = Client(paths)
    whole.catch_up("main")
    assert a.seen == b.seen == whole.seen and len(a.seen) >= 12
    assert a.kinds == b.kinds and a.turns == b.turns


def test_a_rewritten_file_answers_reset_and_never_reads_from_the_middle_of_a_line(tmp_path: Path, switch) -> None:
    main = _main(tmp_path)
    append(main, turn(0, "a") + turn(10, "b"))
    first = reading.read_forward(str(main), CONV, "main", None)
    held = cursors.Cursor(CONV, "main", first.end, first.last_serial or "")
    assert first.reset is None and first.events
    ctx_cache.clear()
    main.write_bytes(b"")
    append(main, [user(0, "a completely different and much longer first prompt than before"), user(1, "x")] + turn(20, "z") * 3)
    again = reading.read_forward(str(main), CONV, "main", held)
    assert again.reset == "file_rewritten" and again.events == []
    main.write_bytes(main.read_bytes()[:20])
    cut = reading.read_forward(str(main), CONV, "main", held)
    assert cut.reset == "truncated" and cut.events == []


def test_a_rewritten_file_reaches_the_hook_as_a_reset_batch(tmp_path: Path, switch) -> None:
    main = _main(tmp_path)
    got: List[subscribe.TimelineBatch] = []
    subscribe.subscribe(None, got.append)
    append(main, turn(0, "a") + turn(10, "b"))
    step(main)
    main.write_bytes(b"")
    append(main, [user(0, "different") for _ in range(3)] + turn(30, "q") * 2)
    step(main)
    assert got[-1].reset == "file_rewritten" and got[-1].events


def test_a_5_mib_line_is_one_stub_event_and_the_cursor_moves_past_it(tmp_path: Path, switch) -> None:
    main = _main(tmp_path)
    huge = {"type": "user", "uuid": "huge-1", "timestamp": "2026-11-01T10:00:05.000Z",
            "message": {"role": "user", "content": "x" * (5 * 1024 * 1024 + 1000)}}
    append(main, turn(0, "a") + [huge] + turn(20, "b"))
    pages, held = [], None
    while True:
        page = reading.read_forward(str(main), CONV, "main", held)
        pages.append(page)
        held = cursors.Cursor(CONV, "main", page.end, page.last_serial or "")
        if page.at_end:
            break
    events = [e for page in pages for e in page.events]
    stubs = [e for e in events if e.data.get("oversize")]
    assert len(stubs) == 1 and stubs[0].kind is Kind.PROMPT and stubs[0].data["bytes"] > 5 * 1024 * 1024
    assert not any("x" * 100 in json.dumps(e.model_dump(mode="json")) for e in events)
    assert pages[-1].end == main.stat().st_size and len(pages) >= 2
    at_stub = cursors.Cursor(CONV, "main", stubs[0].pos.offset, stubs[0].pos.serial)
    after = reading.read_forward(str(main), CONV, "main", at_stub)
    assert after.reset is None and [e.kind for e in after.events][0] is Kind.PROMPT and not any(e.data.get("oversize") for e in after.events)


def test_an_agent_files_append_moves_the_frame_and_reaches_the_hook(tmp_path: Path, frames, switch) -> None:
    sent, clock = frames
    main = _main(tmp_path)
    agent = main.with_suffix("") / "subagents" / "agent-a1.jsonl"
    append(main, turn(0, "a"))
    append(agent, [user(1, "agent prompt")])
    got: List[subscribe.TimelineBatch] = []
    subscribe.subscribe(None, got.append)
    assert agent_tail.TAILS.poll(str(main), CONV) == 0
    assert sent == [] and got == []
    append(agent, [user(2, "agent step"), user(3, "agent step two")])
    assert agent_tail.TAILS.poll(str(main), CONV) == 1
    assert [b.file_key for b in got] == ["a1"] and len(got[0].events) == 2 and got[0].events[0].thread == "agent:a1"
    assert len(sent) == 1 and set(sent[0]["moved"]) == {"a1"}
    offset, serial = sent[0]["moved"]["a1"]
    assert offset == agent.stat().st_size and serial
    append(main, turn(10, "b"))
    step(main)
    clock.advance(2.0)
    append(agent, [user(4, "agent step three")])
    agent_tail.TAILS.poll(str(main), CONV)
    clock.advance(2.0)
    assert set(sent[-1]["moved"]) == {"a1"} and sent[-1]["moved"]["a1"][0] == agent.stat().st_size


def test_the_serial_check_catches_a_rewrite_that_keeps_every_offset(tmp_path: Path, switch) -> None:
    main = _main(tmp_path)
    append(main, [{"type": "user", "uuid": "aaaa", "message": {"role": "user", "content": "one"}},
                  {"type": "user", "uuid": "bbbb", "message": {"role": "user", "content": "two"}}])
    first = reading.read_forward(str(main), CONV, "main", None)
    held = cursors.Cursor(CONV, "main", first.end, first.last_serial or "")
    assert held.serial == "bbbb"
    body = main.read_bytes().replace(b'"uuid":"bbbb"', b'"uuid":"cccc"')
    main.write_bytes(body)
    append(main, [{"type": "user", "uuid": "dddd", "message": {"role": "user", "content": "three"}}])
    assert len(body) == held.offset
    assert reading.read_forward(str(main), CONV, "main", held).reset == "file_rewritten"


def test_a_hot_step_is_a_batch_that_continues_the_position_and_a_jump_is_a_gap(tmp_path: Path, switch) -> None:
    main = _main(tmp_path)
    got: List[subscribe.TimelineBatch] = []
    subscribe.subscribe({Kind.REPLY}, got.append)
    append(main, turn(0, "a"))
    step(main)
    append(main, turn(10, "b"))
    step(main)
    assert [b.to_pos.offset for b in got] == sorted(b.to_pos.offset for b in got)
    assert got[1].from_pos == got[0].to_pos
    assert all(e.kind is Kind.REPLY for b in got for e in b.events) and got[1].events
    assert got[-1].session_uuid and got[-1].conv == CONV


def test_the_hot_driver_state_is_what_the_state_projection_carries(tmp_path: Path, switch) -> None:
    main = _main(tmp_path)
    append(main, turn(0, "a"))
    step(main)
    seen: Dict[str, Any] = {}
    from src.core.timeline import state as projection
    from src.core.timeline.facts_adapter import facts_from_state

    def read(state: Any, serial: Any) -> bool:
        seen.update(projection.transcript_fields(state, facts_from_state(state, size=state.cursor)))
        return True

    assert hot.DRIVER.with_state(str(main.resolve()), read) is True
    assert seen["open_agents"] == 0 and seen["coverage"] == "whole" and seen["newest_append_at"]


def test_the_live_feeds_look_wakes_the_agent_files_so_an_agent_only_append_moves_the_frame(tmp_path: Path, frames, switch) -> None:
    from types import SimpleNamespace

    from src.core.pipeline.feed import LiveFeed

    sent, _clock = frames
    main = _main(tmp_path)
    agent = main.with_suffix("") / "subagents" / "agent-a1.jsonl"
    append(main, turn(0, "a"))
    append(agent, [user(1, "agent prompt")])
    engine = SimpleNamespace(observer=SimpleNamespace(session_changed=lambda *_a, **_k: 0))
    feed = LiveFeed(paths_for=lambda: (lambda sid: (str(main), str(agent.parent))), engine=lambda: engine)
    feed.look("ses_1", engine)
    agent_tail.TAILS.drain()
    assert sent == []
    append(agent, [user(2, "agent step")])
    feed.look("ses_1", engine)
    agent_tail.TAILS.drain()
    assert len(sent) == 1 and set(sent[0]["moved"]) == {"a1"}
