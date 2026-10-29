
from __future__ import annotations

import asyncio
import os
import resource
from datetime import datetime, timezone
from typing import List, Set

import pytest

from src.core.attention import fs_trigger
from src.core.attention.fs_trigger import Coalescer, FsTrigger, descriptor_budget
from src.core.attention.ledger import AttentionLedger
from src.core.attention.watcher import AttentionWatcher, WatchTarget

needs_kqueue = pytest.mark.skipif(
    not fs_trigger.KQUEUE_AVAILABLE, reason="no kqueue on this platform")




def test_a_burst_releases_once_after_it_goes_quiet() -> None:
    c = Coalescer(quiet=0.15, max_wait=1.0)
    for at in (0.0, 0.05, 0.10):
        c.note({"a"}, at)
    assert c.due_at() == pytest.approx(0.25)
    assert c.take(0.2) == set()
    assert c.take(0.25) == {"a"}
    assert c.due_at() is None and c.take(9.0) == set()


def test_a_stream_that_never_pauses_still_releases_at_the_cap() -> None:
    c = Coalescer(quiet=0.15, max_wait=1.0)
    at = 0.0
    while at < 0.95:
        c.note({"a"}, at)
        at += 0.05
    c.note({"b"}, 0.99)
    assert c.due_at() == pytest.approx(1.0)
    assert c.take(1.0) == {"a", "b"}


def test_an_empty_note_arms_nothing() -> None:
    c = Coalescer(quiet=0.1, max_wait=1.0)
    c.note(set(), 0.0)
    assert c.due_at() is None


def test_the_descriptor_budget_is_a_share_of_the_limit(monkeypatch) -> None:
    monkeypatch.setattr(resource, "getrlimit", lambda _r: (256, 1024))
    assert descriptor_budget(64) == 64
    monkeypatch.setattr(resource, "getrlimit", lambda _r: (40, 1024))
    assert descriptor_budget(64) == 10
    monkeypatch.setattr(resource, "getrlimit", lambda _r: (3, 1024))
    assert descriptor_budget(64) == 0




async def _collect(trigger_kwargs: dict, body) -> List[Set[str]]:
    fired: List[Set[str]] = []
    trigger = FsTrigger(fired.append, **trigger_kwargs)
    assert trigger.start()
    try:
        await body(trigger)
    finally:
        trigger.close()
    return fired


def _rewrite(path, text: str) -> None:
    with open(path, "r+") as handle:
        handle.seek(0)
        handle.truncate()
        handle.write(text)


@needs_kqueue
def test_an_in_place_rewrite_burst_fires_once_with_its_sessions(tmp_path) -> None:
    record, other = tmp_path / "7.json", tmp_path / "8.json"
    record.write_text("{}")
    other.write_text("{}")

    async def body(trigger: FsTrigger) -> None:
        trigger.rearm({str(record): ["ses_a", "ses_b"]})
        for n in range(5):
            _rewrite(record, '{"status": "busy%d"}' % n)
            await asyncio.sleep(0.01)
        other.write_text("{}")
        await asyncio.sleep(0.3)

    fired = asyncio.run(_collect({"quiet_seconds": 0.05, "max_wait_seconds": 1.0}, body))
    assert fired == [{"ses_a", "ses_b"}]


@needs_kqueue
def test_an_unwatched_change_fires_nothing(tmp_path) -> None:
    record = tmp_path / "7.json"
    record.write_text("{}")

    async def body(trigger: FsTrigger) -> None:
        trigger.rearm({})
        _rewrite(record, "{1}")
        await asyncio.sleep(0.15)

    assert asyncio.run(_collect({"quiet_seconds": 0.02}, body)) == []


@needs_kqueue
def test_a_directory_entry_appearing_fires(tmp_path) -> None:
    subagents = tmp_path / "u" / "subagents"
    subagents.mkdir(parents=True)

    async def body(trigger: FsTrigger) -> None:
        trigger.rearm({str(subagents): ["ses_a"]})
        (subagents / "agent-1.jsonl").write_text("{}\n")
        await asyncio.sleep(0.15)

    assert asyncio.run(_collect({"quiet_seconds": 0.02}, body)) == [{"ses_a"}]


@needs_kqueue
def test_a_replaced_file_is_dropped_and_rearmed(tmp_path) -> None:
    record = tmp_path / "7.json"
    record.write_text("{}")

    async def body(trigger: FsTrigger) -> None:
        trigger.rearm({str(record): ["ses_a"]})
        staged = tmp_path / "7.json.tmp"
        staged.write_text('{"new": 1}')
        os.replace(staged, record)
        await asyncio.sleep(0.15)
        assert trigger.watched_paths() == []
        trigger.rearm({str(record): ["ses_a"]})
        assert trigger.watched_paths() == [str(record)]
        _rewrite(record, '{"new": 2}')
        await asyncio.sleep(0.15)

    fired = asyncio.run(_collect({"quiet_seconds": 0.02}, body))
    assert fired == [{"ses_a"}, {"ses_a"}]


@needs_kqueue
def test_rearm_closes_what_is_no_longer_wanted(tmp_path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_text("")
    b.write_text("")

    async def body(trigger: FsTrigger) -> None:
        trigger.rearm({str(a): ["s1"], str(b): ["s2"]})
        assert sorted(trigger.watched_paths()) == [str(a), str(b)]
        trigger.rearm({str(b): ["s2"]})
        assert trigger.watched_paths() == [str(b)]
        _rewrite(a, "x")
        await asyncio.sleep(0.15)

    assert asyncio.run(_collect({"quiet_seconds": 0.02}, body)) == []


@needs_kqueue
def test_the_cap_holds_and_keeps_the_most_recently_active(tmp_path) -> None:
    paths = [tmp_path / name for name in ("a", "b", "c")]
    for path in paths:
        path.write_text("")
    a, b, c = (str(p) for p in paths)

    async def body(trigger: FsTrigger) -> None:
        trigger.rearm({a: ["s1"], b: ["s2"]})
        _rewrite(paths[1], "busy")
        await asyncio.sleep(0.1)
        trigger.rearm({a: ["s1"], b: ["s2"], c: ["s3"]})
        watched = trigger.watched_paths()
        assert len(watched) == 2 and b in watched
        trigger.rearm({str(tmp_path / "missing"): ["s9"]})
        assert trigger.watched_paths() == []

    asyncio.run(_collect({"quiet_seconds": 0.02, "max_paths": 2}, body))


def test_no_kqueue_falls_back_and_says_so_once(monkeypatch) -> None:
    events: List[str] = []
    monkeypatch.setattr(fs_trigger, "KQUEUE_AVAILABLE", False)
    monkeypatch.setattr(fs_trigger.logger, "info",
                        lambda event, **_kw: events.append(event))

    async def drive() -> bool:
        trigger = FsTrigger(lambda _k: None)
        started = trigger.start() or trigger.start()
        trigger.rearm({"/nowhere": ["s"]})
        trigger.close()
        return started

    assert asyncio.run(drive()) is False
    assert events == ["attention_fs_trigger_unavailable"]


def test_no_descriptor_budget_falls_back() -> None:
    async def drive() -> bool:
        return FsTrigger(lambda _k: None, max_paths=0).start()

    assert asyncio.run(drive()) is False




def _watcher(read_log: List[str], **kw) -> AttentionWatcher:
    targets = [WatchTarget("ses_a", "k_a"), WatchTarget("ses_b", "k_b")]

    def read(target: WatchTarget, now: datetime):
        read_log.append(target.session_id)
        return None

    return AttentionWatcher(
        list_targets=lambda: targets, read_evidence=read,
        raise_toast=lambda *a: None, set_unread=lambda *a: None,
        on_busy_edge=lambda *a: None, ledger=AttentionLedger(),
        now=lambda: datetime(2026, 9, 26, tzinfo=timezone.utc),
        registry_directory="/nonexistent-762", **kw,
    )


def test_a_targeted_pass_reads_only_the_woken_session_and_is_not_a_cycle() -> None:
    reads: List[str] = []
    watcher = _watcher(reads)

    async def drive() -> None:
        await watcher.tick_once()
        cycles = watcher._cycles
        reads.clear()
        await watcher.tick_sessions({"ses_b", "ses_unknown"})
        assert reads == ["ses_b"]
        assert watcher._cycles == cycles

    asyncio.run(drive())


def test_a_file_wake_runs_a_targeted_pass_until_the_full_one_is_due() -> None:
    reads: List[str] = []
    watcher = _watcher(reads, tick_seconds=30.0, watch_paths=lambda ids: {})

    async def drive() -> List[str]:
        await watcher._next_pass()
        assert sorted(reads) == ["ses_a", "ses_b"]
        reads.clear()
        watcher._wake.files_changed({"ses_a"})
        assert await asyncio.wait_for(watcher._wait_for_work(), 1.0) == "files"
        await watcher._next_pass()
        return reads

    assert asyncio.run(drive()) == ["ses_a"]


def test_a_poke_still_forces_a_full_pass() -> None:
    reads: List[str] = []
    watcher = _watcher(reads, tick_seconds=30.0, watch_paths=lambda ids: {})

    async def drive() -> List[str]:
        await watcher._next_pass()
        reads.clear()
        watcher._wake.files_changed({"ses_a"})
        watcher.poke("k_b")
        assert await watcher._wait_for_work() == "poke"
        await watcher._next_pass()
        return sorted(reads)

    assert asyncio.run(drive()) == ["ses_a", "ses_b"]


def test_the_backstop_still_times_out_with_no_file_events() -> None:
    watcher = _watcher([], tick_seconds=0.05, watch_paths=lambda ids: {})

    async def drive() -> str:
        await watcher._next_pass()
        return await asyncio.wait_for(watcher._wait_for_work(), 1.0)

    assert asyncio.run(drive()) == "tick"


@needs_kqueue
def test_a_turn_short_of_its_quiet_window_gets_one_settle_reread() -> None:
    from datetime import timedelta

    from src.core.attention.evidence import Evidence, FAMILY_CLAUDE
    from src.core.attention.registry_record import parse_registry_record
    from src.core.attention.resolve import DONE_QUIET_SECONDS
    from src.core.attention.transcript_facts import FACTS_FOUND, TranscriptFacts
    from src.core.session_status import LIVENESS_LIVE

    now = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)
    quiet = DONE_QUIET_SECONDS - 0.2

    def read(_target: WatchTarget, at: datetime) -> Evidence:
        return Evidence(
            tmux_liveness=LIVENESS_LIVE, agent_family=FAMILY_CLAUDE,
            registry=parse_registry_record(
                {"pid": 1, "status": "busy", "version": "2.1.283"}, path_pid=None),
            transcript=TranscriptFacts(verdict=FACTS_FOUND,
                                       newest_append_at=now - timedelta(seconds=quiet)),
            pane=None, now=now)

    watcher = AttentionWatcher(
        list_targets=lambda: [WatchTarget("ses_a", "k_a")], read_evidence=read,
        raise_toast=lambda *a: None, set_unread=lambda *a: None,
        on_busy_edge=lambda *a: None, ledger=AttentionLedger(), now=lambda: now,
        registry_directory="/nonexistent-762", tick_seconds=30.0,
        watch_paths=lambda ids: {})

    async def drive() -> str:
        watcher._open_watch()
        try:
            await watcher._next_pass()
            assert watcher._wake._later == {}
            await watcher.tick_sessions({"ses_a"})
            assert set(watcher._wake._later) == {"ses_a"}
            return await asyncio.wait_for(watcher._wait_for_work(), 1.0)
        finally:
            watcher._close_watch()

    assert asyncio.run(drive()) == "files"
