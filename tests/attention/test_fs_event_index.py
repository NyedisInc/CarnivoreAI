
import asyncio
import glob
import os

import pytest

from src.core import fs_event_index
from src.core.attention import codex_gather
from src.core.attention.wake import WakeSources

UUID = "019a1b2c-3d4e-5f60-7182-93a4b5c6d7e8"


async def _until(predicate, seconds=10.0):
    end = asyncio.get_running_loop().time() + seconds
    while not predicate():
        assert asyncio.get_running_loop().time() < end, "timed out"
        await asyncio.sleep(0.05)


def test_kinds_newest_refresh_and_scan_event_race(tmp_path):
    codex = tmp_path / "sessions" / "2026" / "10" / "28"
    claude = tmp_path / "projects" / "-x"
    codex.mkdir(parents=True)
    claude.mkdir(parents=True)
    old = codex / f"rollout-2026-10-28T09-00-00-{UUID}.jsonl"
    new = codex / f"rollout-2026-10-28T10-00-00-{UUID}.jsonl"
    bare = claude / f"{UUID}.jsonl"
    for f in (old, new, bare):
        f.write_text("{}\n")
    index = fs_event_index.FsEventIndex([str(tmp_path / "sessions"), str(tmp_path / "projects")])
    index._scan()
    assert index.lookup(UUID, fs_event_index.CODEX) == str(new)
    assert index.lookup(UUID, fs_event_index.CLAUDE) == str(bare)
    bare.write_text("{}\n" * 50)
    index._scan()
    assert index.entry(UUID, fs_event_index.CLAUDE)[1] == bare.stat().st_size
    late = codex / "rollout-2026-10-28T11-00-00-019a1b2c-3d4e-5f60-7182-93a4b5c6d7e9.jsonl"
    original_walk = index._walk

    def walk_then_event(seen, known):
        original_walk(seen, known)
        late.write_text("{}\n")
        index._apply(str(late))

    index._walk = walk_then_event
    index._scan()
    assert index.lookup("019a1b2c-3d4e-5f60-7182-93a4b5c6d7e9") == str(late)


@pytest.mark.asyncio
async def test_real_wiring_lookup_wake_and_late_root(tmp_path, monkeypatch):
    projects = tmp_path / "projects" / "-x"
    projects.mkdir(parents=True)
    codex_root = tmp_path / "codex" / "sessions"
    monkeypatch.setattr(
        fs_event_index, "default_roots", lambda: (str(tmp_path / "projects"), str(codex_root))
    )
    monkeypatch.setattr(fs_event_index, "RESCAN_SECONDS", 1.0)
    monkeypatch.setattr(fs_event_index, "_index", None)
    monkeypatch.setattr(fs_event_index, "_task", None)
    (tmp_path / "registry").mkdir()
    wake = WakeSources(str(tmp_path / "registry"), watch_files=True)
    wake.open()
    index = fs_event_index.current()
    try:
        await _until(lambda: index.ready and index.watching)
        assert not index.serves(str(codex_root / "x"))
        transcript = projects / "ses.jsonl"
        transcript.write_text("{}\n")
        kqueue_calls = []
        real_rearm = wake.trigger.rearm
        wake.trigger.rearm = lambda d: (kqueue_calls.append(dict(d)), real_rearm(d))[1]
        wake.rearm({str(transcript): {"ses_1"}})
        assert kqueue_calls == [{}]
        await asyncio.sleep(0.3)
        transcript.write_text("{}\n{}\n")
        await _until(lambda: "ses_1" in wake.take_files())

        day = codex_root / "2026" / "10" / "28"
        day.mkdir(parents=True)
        rollout = day / f"rollout-2026-10-28T09-00-00-{UUID}.jsonl"
        rollout.write_text("{}\n")
        await _until(lambda: index.serves(str(rollout)), seconds=15)
        monkeypatch.setattr(glob, "glob", lambda *a, **k: pytest.fail("glob called"))
        await _until(lambda: index.lookup(UUID))
        assert codex_gather.rollout_path_in_sessions(str(tmp_path / "codex"), UUID) == str(rollout)
        assert codex_gather.rollout_path_in_sessions(str(tmp_path / "codex"), "ses") is None
    finally:
        wake.close()
        assert not index._subscribers
        index.stop()
        await asyncio.sleep(0.5)
