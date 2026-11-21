
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, List

import pytest

from src.core.attention.transcript_facts import TranscriptFacts
from src.core.product_identity import env_names
from src.core.timeline import agent_tail, ctx_cache, cursor as cursors, gate, hot, reading, subscribe
from src.core.timeline.context import ExtractContext
from src.core.timeline.push import FrameCoalescer
from tests.python.timeline.exposure_helpers import CONV, Clock, append, step, turn, user

WAIT = 3.0


def _main(tmp_path: Path) -> Path:
    return tmp_path / "proj" / f"{CONV}.jsonl"


def _agent(main: Path, name: str = "a1") -> Path:
    return main.with_suffix("") / "subagents" / f"agent-{name}.jsonl"


def _drain() -> int:
    return agent_tail.TAILS.drain()



def test_finding1_a_blocked_agent_poll_never_delays_the_watchers_read(tmp_path: Path, frames, switch, monkeypatch: pytest.MonkeyPatch) -> None:
    main = _main(tmp_path)
    append(main, turn(0, "a"))
    append(_agent(main), [user(1, "x")])
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def blocked(_self: Any, _main_real: str, _conv: str, _family: str = "claude") -> int:
        entered.set()
        release.wait(10)
        return 0

    monkeypatch.setattr(agent_tail.AgentTails, "poll", blocked)
    monkeypatch.setattr(agent_tail.TAILS, "worker_enabled", True, raising=False)
    stat = main.stat()

    def watcher() -> None:
        hot.shadow_read(str(main), (stat.st_mtime_ns, stat.st_size), TranscriptFacts(verdict="found"))
        finished.set()

    thread = threading.Thread(target=watcher, daemon=True)
    thread.start()
    try:
        assert finished.wait(WAIT), "the watcher's read waited on the agent poll"
        assert entered.wait(WAIT), "the agent poll never ran (it must run on the worker)"
    finally:
        release.set()
        thread.join(WAIT)
        agent_tail.TAILS.clear()


def test_finding1_the_worker_polls_what_wake_queued_and_clear_stops_it(tmp_path: Path, frames, switch, monkeypatch: pytest.MonkeyPatch) -> None:
    sent, _clock = frames
    main, agent = _main(tmp_path), _agent(_main(tmp_path))
    append(main, turn(0, "a"))
    append(agent, [user(1, "x")])
    monkeypatch.setattr(agent_tail.TAILS, "worker_enabled", True, raising=False)
    try:
        agent_tail.wake(str(main), CONV)
        deadline = threading.Event()
        for _ in range(60):
            if any(tail.agents for tail in agent_tail.TAILS._tails.values()):  # noqa: SLF001
                break
            deadline.wait(0.05)
        append(agent, [user(2, "y")])
        agent_tail.wake(str(main), CONV)
        for _ in range(60):
            if sent:
                break
            deadline.wait(0.05)
        assert len(sent) == 1 and set(sent[0]["moved"]) == {"a1"}
    finally:
        agent_tail.TAILS.clear()
    assert agent_tail.TAILS._worker is None  # noqa: SLF001


def test_finding1_one_conversations_blocked_poll_does_not_hold_up_another(tmp_path: Path, switch, monkeypatch: pytest.MonkeyPatch) -> None:
    mains = [tmp_path / f"p{i}" / f"{CONV[:-1]}{i}.jsonl" for i in (1, 2)]
    for main in mains:
        append(main, turn(0, "a"))
        append(_agent(main), [user(1, "x")])
    tails = agent_tail.AgentTails()
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    real_last = agent_tail.read_last_line

    def slow(path: Any, size: int, **kwargs: Any) -> Any:
        if "/p1/" in str(path):
            entered.set()
            release.wait(10)
        return real_last(path, size, **kwargs)

    monkeypatch.setattr(agent_tail, "read_last_line", slow)
    first = threading.Thread(target=tails.poll, args=(str(mains[0]), "c1"), daemon=True)
    first.start()
    assert entered.wait(WAIT)
    second = threading.Thread(target=lambda: (tails.poll(str(mains[1]), "c2"), done.set()), daemon=True)
    second.start()
    try:
        assert done.wait(WAIT), "a blocked poll of one conversation held up another conversation"
    finally:
        release.set()
        first.join(WAIT)


def test_finding1_without_a_listener_an_agent_append_moves_the_frame_but_extracts_nothing(tmp_path: Path, frames, switch,
                                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    sent, clock = frames
    main, agent = _main(tmp_path), _agent(_main(tmp_path))
    append(main, turn(0, "a"))
    append(agent, [user(1, "agent prompt")])
    agent_tail.TAILS.poll(str(main), CONV)
    append(agent, [user(2, "agent step"), user(3, "agent step two")])
    extracted: List[str] = []
    for name in ("read_from", "warm_context"):
        real = getattr(reading, name)
        monkeypatch.setattr(reading, name, lambda *a, _real=real, _name=name, **k: extracted.append(_name) or _real(*a, **k))
    assert agent_tail.TAILS.poll(str(main), CONV) == 1
    assert extracted == [], "an agent append with no listener ran the extractor"
    assert len(sent) == 1 and sent[0]["moved"]["a1"][0] == agent.stat().st_size and sent[0]["moved"]["a1"][1]
    got: List[subscribe.TimelineBatch] = []
    subscribe.subscribe(None, got.append)
    clock.advance(2.0)
    append(agent, [user(4, "agent step three")])
    agent_tail.TAILS.poll(str(main), CONV)
    assert extracted and len(got) == 1 and len(got[0].events) == 1



@pytest.mark.parametrize("trigger", ["shadow_read", "wake"])
def test_finding7_switching_off_empties_every_structure_and_stops_the_frames(tmp_path: Path, frames, switch, monkeypatch: pytest.MonkeyPatch,
                                                                              trigger: str) -> None:
    sent, clock = frames
    monkeypatch.setattr(hot, "GATE_TTL_SECONDS", 0.0)
    monkeypatch.setattr(gate, "HOOK_TTL_SECONDS", 0.0)
    main, agent = _main(tmp_path), _agent(_main(tmp_path))
    append(main, turn(0, "a"))
    append(agent, [user(1, "x")])
    stat = main.stat()
    key = (stat.st_mtime_ns, stat.st_size)
    hot.shadow_read(str(main), key, TranscriptFacts(verdict="found"))
    agent_tail.TAILS.poll(str(main.resolve()), CONV)
    append(agent, [user(2, "y")])
    agent_tail.TAILS.poll(str(main.resolve()), CONV)
    ctx_cache.put("/f", 1, ExtractContext(conv="c"))
    subscribe.CONVERSATIONS._map["x"] = "y"  # noqa: SLF001
    assert subscribe._states and agent_tail.TAILS._tails and ctx_cache._slots and len(hot.DRIVER)  # noqa: SLF001
    sent_before = len(sent)
    switch.on = False
    if trigger == "shadow_read":
        hot.shadow_read(str(main), key, TranscriptFacts(verdict="found"))
    else:
        agent_tail.wake(str(main), CONV)
    assert not subscribe._states and not agent_tail.TAILS._tails and not ctx_cache._slots  # noqa: SLF001
    assert not subscribe.CONVERSATIONS._map  # noqa: SLF001
    append(main, turn(10, "b"))
    step(main)
    clock.advance(5.0)
    assert len(sent) == sent_before



def test_finding9_a_cursor_after_a_huge_line_is_not_re_read_and_re_parsed_on_every_poll(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.core.transcript_manifest.tail as tail

    path = tmp_path / "huge.jsonl"
    first = b'{"type":"user","uuid":"a"}\n'
    head = b'{"type":"user","uuid":"huge-1","message":{"role":"user","content":"'
    path.write_bytes(first + head + b"x" * (5 * 1024 * 1024 + 1000) + b'"}}\n')
    held = cursors.Cursor(CONV, "main", path.stat().st_size, "huge-1")
    parses: List[int] = []
    real = tail.line_serial
    monkeypatch.setattr(tail, "line_serial", lambda line: parses.append(len(line)) or real(line))
    assert [cursors.check(str(path), held) for _ in range(3)] == [None, None, None]
    assert len(parses) == 1, f"the huge line was parsed {len(parses)} times for 3 checks"
    with open(path, "r+b") as handle:
        handle.seek(len(first) + len(b'{"type":"user","uuid":"'))
        handle.write(b"huge-2")
    assert cursors.check(str(path), held) == "file_rewritten"



def test_lowc_an_off_gate_resolves_no_path_in_the_live_feed(tmp_path: Path, switch, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from src.core.pipeline.feed import LiveFeed

    switch.on = False
    main = _main(tmp_path)
    append(main, turn(0, "a"))
    append(_agent(main), [user(1, "x")])
    counted: List[str] = []
    real = os.path.realpath
    monkeypatch.setattr(os.path, "realpath", lambda p, *a, **k: counted.append(str(p)) or real(p, *a, **k))
    engine = SimpleNamespace(observer=SimpleNamespace(session_changed=lambda *_a, **_k: 0))
    feed = LiveFeed(paths_for=lambda: (lambda sid: (str(main), str(_agent(main).parent))), engine=lambda: engine)
    feed.look("ses_1", engine)
    assert counted.count(str(main)) == 1


def test_lowe_the_remembered_sessions_are_evicted_least_recently_used_first(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.timeline import push

    monkeypatch.setattr(push, "MAX_REMEMBERED", 3)
    clock, sent = Clock(), []
    pusher = FrameCoalescer(lambda frame: sent.append(frame) or True, clock.now, clock.later)
    for name in ("s1", "s2", "s3"):
        pusher.add(name, "c", "main", (1, "a"), {}, None)
        clock.advance(2.0)
    pusher.add("s1", "c", "main", (2, "b"), {}, None)
    clock.advance(2.0)
    pusher.add("s4", "c", "main", (1, "a"), {}, None)
    assert {slot[0] for slot in pusher._last_sent} == {"s1", "s3", "s4"}  # noqa: SLF001


def test_lowf_status_source_legacy_turns_the_whole_hook_off_main_frames_and_agent_frames_alike(tmp_path: Path, frames, switch,
                                                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    sent, clock = frames
    main, agent = _main(tmp_path), _agent(_main(tmp_path))
    append(main, turn(0, "a"))
    append(agent, [user(1, "x")])
    agent_tail.TAILS.poll(str(main.resolve()), CONV)
    monkeypatch.setenv(env_names(hot.STATUS_SOURCE_ENV)[0], "legacy")
    gate.reset_hook_gate()
    hot.reset_gate()
    stat = main.stat()
    append(agent, [user(2, "y")])
    hot.shadow_read(str(main), (stat.st_mtime_ns, stat.st_size), TranscriptFacts(verdict="found"))
    agent_tail.wake(str(main), CONV)
    _drain()
    clock.advance(5.0)
    assert sent == []
    monkeypatch.delenv(env_names(hot.STATUS_SOURCE_ENV)[0])
    gate.reset_hook_gate()
    agent_tail.wake(str(main), CONV)
    _drain()
    assert len(sent) == 1 and set(sent[0]["moved"]) == {"a1"}
