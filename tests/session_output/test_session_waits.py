
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from src.core.cross_session_search import strip_ansi
from src.core.session_output import cursor as pipe_cursor
from src.core.session_output import waits
from src.core.session_output.tap import OutputTap
from src.core.stream_redactor import redact_whole

SID = "ses_w"


def _decode(raw: bytes) -> str:
    return strip_ansi(raw.decode("utf-8", errors="replace")).replace("\r", "")


class Pane:

    def __init__(self, path: Path, tap: OutputTap) -> None:
        self.path, self.tap, self.stamp = path, tap, 100.0
        path.write_bytes(b"")

    def basis(self):
        return self.path, self.stamp

    def write(self, data: bytes) -> None:
        with open(self.path, "ab") as fh:
            fh.write(data)
        self.tap.emit(SID, data)

    def rotate(self) -> None:
        os.truncate(self.path, 0)
        self.stamp += 1.0


@pytest.fixture
def env(tmp_path):
    tap = OutputTap()
    registry = waits.WaitRegistry(tap)
    return registry, tap, Pane(tmp_path / "s.pipe", tap)


def _wait(registry, pane, spec, *, status="working", since=None, caller="pane:lead:0", gone=lambda: False):
    return waits.run_wait(registry=registry, session_id=SID, caller=caller, spec=spec, initial_status=status,
                          pipe=waits.PipeSource(pane.basis) if pane else None, since=since, is_gone=gone,
                          decode=_decode, clean=redact_whole)



def test_state_names_map_onto_the_eight_display_states():
    assert waits.WaitSpec(("idle", "waiting")).display_states() == {"idle", "finished_unread", "notice"}
    assert waits.STATE_SETS["blocked"] == {"question"} and waits.STATE_SETS["exited"] == {"dead"}


@pytest.mark.asyncio
async def test_a_status_edge_wakes_the_wait_and_names_the_state(env):
    registry, _tap, pane = env
    task = asyncio.create_task(_wait(registry, pane, waits.WaitSpec(("idle",), timeout=5)))
    await asyncio.sleep(0.05)
    registry.on_status(SID, "finished_unread")
    out = await asyncio.wait_for(task, 1.0)
    assert (out.status, out.matched, out.state) == ("matched", "state:idle", "finished_unread")


@pytest.mark.asyncio
async def test_min_quiet_ignores_a_flicker_and_matches_a_state_that_holds(env):
    registry, _tap, pane = env
    task = asyncio.create_task(_wait(registry, pane, waits.WaitSpec(("idle",), timeout=5, min_quiet=0.4)))
    await asyncio.sleep(0.05)
    registry.on_status(SID, "idle")
    await asyncio.sleep(0.1)
    registry.on_status(SID, "working")
    await asyncio.sleep(0.1)
    assert not task.done()
    started = time.monotonic()
    registry.on_status(SID, "idle")
    out = await asyncio.wait_for(task, 2.0)
    assert out.matched == "state:idle" and time.monotonic() - started >= 0.38



@pytest.mark.asyncio
async def test_a_match_spanning_two_reads_is_found_and_old_output_does_not_count(env):
    registry, _tap, pane = env
    pane.write(b"build done before the wait\n")
    task = asyncio.create_task(_wait(registry, pane, waits.WaitSpec(text="build done", timeout=5)))
    await asyncio.sleep(0.05)
    pane.write(b"compiling\nbuild \x1b[32md")
    await asyncio.sleep(waits.MIN_READ_INTERVAL_SECONDS + 0.1)
    assert not task.done()
    pane.write(b"one\r\nnext line\n")
    out = await asyncio.wait_for(task, 2.0)
    assert out.status == "matched" and out.matched == "output"
    assert out.tail.endswith("build done") and "before the wait" not in out.tail


@pytest.mark.asyncio
async def test_still_waiting_hands_back_a_cursor_that_loses_nothing(env):
    registry, _tap, pane = env
    first = await _wait(registry, pane, waits.WaitSpec(text="ready", timeout=1))
    assert first.status == "still_waiting" and first.cursor
    pane.write(b"ready\n")
    second = await _wait(registry, pane, waits.WaitSpec(text="ready", timeout=2), since=pipe_cursor.parse(first.cursor))
    assert second.matched == "output"


@pytest.mark.asyncio
async def test_a_rotated_pipe_file_answers_cursor_reset_and_reads_on_from_the_rotation(env):
    registry, _tap, pane = env
    pane.write(b"x" * 100)
    since = pipe_cursor.at_end(pane.path, pane.stamp)
    pane.rotate()
    pane.write(b"y" * 300)
    out = await _wait(registry, pane, waits.WaitSpec(text="zzz", timeout=2), since=since)
    assert out.status == "cursor_reset"
    assert pipe_cursor.parse(out.cursor).offset == 0


def test_cursor_math_for_shrink_inode_and_tag(tmp_path):
    path = tmp_path / "p"
    path.write_bytes(b"abcdef")
    cur = pipe_cursor.at_end(path, 1.0)
    assert pipe_cursor.parse(cur.encode()) == cur and cur.offset == 6
    path.write_bytes(b"ab")
    assert pipe_cursor.read_since(path, 1.0, cur).reset
    other = pipe_cursor.Cursor(cur.inode + 1, cur.stamp_ms, 0)
    assert pipe_cursor.read_since(path, 1.0, other).reset
    for bad in ("", "c2.1.2.3", "c1.1.2", "c1.a.2.3", None, 5):
        with pytest.raises(pipe_cursor.CursorError):
            pipe_cursor.parse(bad)
    big = tmp_path / "big"
    big.write_bytes(b"z" * (pipe_cursor.MAX_READ_BYTES + 10))
    got = pipe_cursor.read_since(big, 1.0, pipe_cursor.Cursor(big.stat().st_ino, 1000, 0))
    assert len(got.data) == pipe_cursor.MAX_READ_BYTES and got.more


@pytest.mark.asyncio
async def test_a_secret_inside_the_match_is_redacted(env):
    registry, _tap, pane = env
    token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    task = asyncio.create_task(_wait(registry, pane, waits.WaitSpec(text="DEPLOYED", timeout=5)))
    await asyncio.sleep(0.05)
    pane.write(f"export GH={token}\nDEPLOYED ok\n".encode())
    out = await asyncio.wait_for(task, 2.0)
    assert out.matched == "output" and token not in out.tail and out.tail.startswith("export GH=*")


@pytest.mark.asyncio
async def test_guard_6_a_regex_shaped_string_is_matched_literally_and_fast(env):
    registry, _tap, pane = env
    task = asyncio.create_task(_wait(registry, pane, waits.WaitSpec(text="(a+)+$", timeout=3)))
    await asyncio.sleep(0.05)
    started = time.monotonic()
    pane.write(b"a" * (60 * 1024) + b"!\n")
    await asyncio.sleep(waits.MIN_READ_INTERVAL_SECONDS + 0.2)
    assert not task.done()
    pane.write(b"literal (a+)+$ here\n")
    out = await asyncio.wait_for(task, 2.0)
    assert out.matched == "output" and time.monotonic() - started < 2.0


@pytest.mark.asyncio
async def test_guard_5_the_answer_is_at_most_40_lines_and_8_kib(env):
    registry, _tap, pane = env
    task = asyncio.create_task(_wait(registry, pane, waits.WaitSpec(text="END", timeout=5)))
    await asyncio.sleep(0.05)
    pane.write(b"".join(b"line %d %s\n" % (i, b"w" * 400) for i in range(200)) + b"END\n")
    out = await asyncio.wait_for(task, 3.0)
    assert out.tail.endswith("END") and out.tail.count("\n") < waits.MAX_TAIL_LINES
    assert len(out.tail.encode()) <= waits.MAX_TAIL_BYTES



@pytest.mark.asyncio
async def test_guard_1_and_2_a_parked_wait_never_blocks_the_loop(env):
    registry, _tap, pane = env
    task = asyncio.create_task(_wait(registry, pane, waits.WaitSpec(("idle",), text="nope", timeout=2)))
    ticks = 0
    started = time.monotonic()
    while time.monotonic() - started < 0.5:
        await asyncio.sleep(0.01)
        ticks += 1
    assert ticks > 25
    assert registry.open_count == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_guard_3_timeout_answers_still_waiting_and_cancel_frees_everything(env):
    registry, tap, pane = env
    out = await _wait(registry, pane, waits.WaitSpec(("idle",), text="x", timeout=1))
    assert out.status == "still_waiting" and 0.9 <= out.elapsed_s < 2.0
    task = asyncio.create_task(_wait(registry, pane, waits.WaitSpec(("idle",), text="x", timeout=30)))
    await asyncio.sleep(0.05)
    assert registry.open_count == 1 and tap.observer_count(SID) == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert registry.open_count == 0 and tap.observer_count(SID) == 0
    registry.on_status(SID, "idle")


@pytest.mark.asyncio
async def test_guard_4_per_caller_and_engine_limits_refuse_at_once_with_retry_after(env, monkeypatch):
    registry, _tap, pane = env
    held = [asyncio.create_task(_wait(registry, None, waits.WaitSpec(("idle",), timeout=20))) for _ in range(4)]
    await asyncio.sleep(0.05)
    with pytest.raises(waits.WaitLimitError) as caught:
        await _wait(registry, None, waits.WaitSpec(("idle",), timeout=5))
    assert 1 <= caught.value.retry_after <= 20
    other = asyncio.create_task(_wait(registry, None, waits.WaitSpec(("idle",), timeout=20), caller="pane:other:0"))
    await asyncio.sleep(0.05)
    assert not other.done()
    monkeypatch.setattr(waits, "MAX_PER_ENGINE", 5)
    with pytest.raises(waits.WaitLimitError):
        await _wait(registry, None, waits.WaitSpec(("idle",), timeout=5), caller="pane:third:0")
    for t in (*held, other):
        t.cancel()
    await asyncio.gather(*held, other, return_exceptions=True)
    assert registry.open_count == 0


@pytest.mark.asyncio
async def test_a_session_that_leaves_answers_session_gone(env):
    registry, _tap, pane = env
    gone = {"now": False}
    task = asyncio.create_task(_wait(registry, pane, waits.WaitSpec(("idle",), timeout=5), gone=lambda: gone["now"]))
    await asyncio.sleep(0.05)
    gone["now"] = True
    registry.on_status(SID, "dead")
    out = await asyncio.wait_for(task, 1.0)
    assert out.status == "session_gone"
