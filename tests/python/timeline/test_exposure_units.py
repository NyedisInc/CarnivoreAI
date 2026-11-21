
from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from src.core.timeline import cursor as cursors, ctx_cache, state as projection, subscribe
from src.core.timeline.context import ExtractContext
from src.core.timeline.identity import ConversationIndex
from src.core.timeline.model import Kind
from src.core.timeline.push import FrameCoalescer
from tests.python.timeline.exposure_helpers import CONV, Clock, append, step, turn


def test_a_cursor_round_trips_and_malformed_ones_are_refused() -> None:
    held = cursors.Cursor("abc", "main", 1204, "sha256:00ff")
    assert cursors.parse(held.wire()) == held
    assert cursors.parse("abc:a1:0:") == cursors.Cursor("abc", "a1", 0, "")
    for bad in ("", "abc:main:5", "abc:main:x:s", "abc:main:5:", "abc:main:0:s", "a b:main:5:s", "abc::5:s"):
        with pytest.raises(cursors.CursorError):
            cursors.parse(bad)


def test_the_line_start_before_an_offset_is_found_across_chunks_and_refused_mid_line(tmp_path: Path) -> None:
    path = tmp_path / "f.jsonl"
    long_line = b"x" * (cursors.BACK_SCAN_CHUNK * 2 + 17)
    path.write_bytes(b"first\n" + long_line + b"\nlast\n")
    end_long = 6 + len(long_line) + 1
    assert cursors.line_start_before(str(path), 6) == 0
    assert cursors.line_start_before(str(path), end_long) == 6
    assert cursors.line_start_before(str(path), end_long + 5) == end_long
    assert cursors.line_start_before(str(path), 7) is None
    assert cursors.line_start_before(str(path), 0) is None


def test_frames_are_at_most_one_per_session_per_second_and_the_last_state_lands() -> None:
    clock, sent = Clock(), []
    pusher = FrameCoalescer(lambda frame: sent.append(frame) or True, clock.now, clock.later)
    pusher.add("s1", "c", "main", (10, "a"), {"open_agents": 1}, None)
    assert len(sent) == 1
    for offset in (20, 30, 40):
        clock.advance(0.2)
        pusher.add("s1", "c", "main", (offset, f"s{offset}"), {"open_agents": offset}, None)
    pusher.add("s1", "c", "a1", (7, "z"), {}, "file_rewritten")
    pusher.add("s2", "c", "main", (5, "q"), {}, None)
    assert len(sent) == 2 and sent[1]["session_uuid"] == "s2"
    clock.advance(1.0)
    assert len(sent) == 3
    assert sent[2]["moved"] == {"main": [40, "s40"], "a1": [7, "z"]} and sent[2]["state"] == {"open_agents": 40} and sent[2]["reset"] == ["a1"]
    assert sent[2]["type"] == "timeline.delta" and not clock.timers


def test_the_hook_narrows_events_by_kind_keeps_positions_and_isolates_a_failing_listener(tmp_path: Path, frames, switch) -> None:
    main = tmp_path / "proj" / f"{CONV}.jsonl"
    seen: List[subscribe.TimelineBatch] = []

    def broken(_batch: subscribe.TimelineBatch) -> None:
        raise RuntimeError("listener bug")

    subscribe.subscribe(None, broken)
    stop = subscribe.subscribe({Kind.TURN_END}, seen.append)
    append(main, turn(0, "a"))
    step(main)
    assert len(seen) == 1 and seen[0].events and {e.kind for e in seen[0].events} == {Kind.TURN_END} and seen[0].to_pos.offset == main.stat().st_size
    stop()
    stop()
    append(main, turn(10, "b"))
    step(main)
    assert len(seen) == 1


def test_state_changes_carry_only_the_changed_fields() -> None:
    assert projection.changed_fields({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": None}) == {"b": 3, "c": None}
    assert projection.changed_fields({}, {"a": 1}) == {"a": 1}


def test_a_context_slot_is_a_copy_so_two_readers_at_one_offset_do_not_share_it() -> None:
    ctx_cache.clear()
    ctx = ExtractContext(conv="c")
    ctx.turn = 5
    ctx_cache.put("/f", 100, ctx)
    ctx.turn = 99
    first, second = ctx_cache.take("/f", 100), ctx_cache.take("/f", 100)
    assert first is not second and first.turn == second.turn == 5 and ctx_cache.take("/f", 101) is None
    ctx_cache.clear()


def test_the_identity_cache_reads_once_per_ttl_and_retries_a_miss_slowly(tmp_path: Path) -> None:
    reads: List[int] = []
    clock = Clock()
    index = ConversationIndex(lambda: tmp_path / "none.db", clock.now)
    original = index._reload

    def counted() -> None:
        reads.append(1)
        original()

    index._reload = counted  # type: ignore[method-assign]
    assert index.session_of("x") is None and index.session_of("x") is None and len(reads) == 1
    clock.advance(3.0)
    index.session_of("x")
    assert len(reads) == 2
