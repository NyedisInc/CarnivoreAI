
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import pytest

from src.core.attention import codex_gather, codex_read_cache, codex_stores

THREAD = "019a0000-0000-7000-8000-000000000001"
CWD = "/work/proj"
NOW = datetime(2026, 11, 18, tzinfo=timezone.utc)


def _write_rollout(home: Path, day: str, uuid: str = THREAD) -> Path:
    folder = home / "sessions" / "2026" / "11" / day
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ("rollout-2026-11-%sT00-00-00-%s.jsonl" % (day, uuid))
    path.write_text('{"type":"event_msg","payload":{"type":"task_started"}}\n')
    return path


def _make_home(tmp_path: Path, *, stored_path: str = "") -> Path:
    home = tmp_path / "codex"
    home.mkdir()
    con = sqlite3.connect(home / "state_5.sqlite")
    con.execute("CREATE TABLE threads (id TEXT, thread_source TEXT, cwd TEXT, name TEXT, archived INT, rollout_path TEXT)")
    con.execute("INSERT INTO threads VALUES (?, 'user', ?, '', 0, ?)", (THREAD, CWD, stored_path))
    con.commit()
    con.close()
    con = sqlite3.connect(home / "thread_history_1.sqlite")
    con.execute("CREATE TABLE thread_turns (thread_id TEXT, status TEXT, rollout_ordinal INT)")
    con.execute("CREATE TABLE thread_history_projection_state (thread_id TEXT, next_rollout_byte_offset INT)")
    con.execute("INSERT INTO thread_turns VALUES (?, 'completed', 1)", (THREAD,))
    con.commit()
    con.close()
    return home


def _cycle(home: Path):
    uuid = codex_stores.resolve_primary_uuid(str(home), pane_current_path=CWD, pane_title="")
    path = codex_gather.rollout_path_for(str(home), THREAD)
    ev = codex_gather.gather_codex_evidence(THREAD, codex_home=str(home), now=NOW)
    return uuid, path, ev.record.verdict


class _Counts:

    def __init__(self) -> None:
        self.scandir = 0
        self.connect = 0


@pytest.fixture
def counts(monkeypatch: pytest.MonkeyPatch) -> _Counts:
    c = _Counts()
    real_scandir, real_connect = os.scandir, sqlite3.connect

    def scandir(*a, **k):
        c.scandir += 1
        return real_scandir(*a, **k)

    def connect(*a, **k):
        c.connect += 1
        return real_connect(*a, **k)

    monkeypatch.setattr(os, "scandir", scandir)
    monkeypatch.setattr(sqlite3, "connect", connect)
    return c


def test_unchanged_cycle_does_no_scans_and_no_connects(tmp_path: Path, counts: _Counts) -> None:
    home = _make_home(tmp_path)
    rollout = _write_rollout(home, "18")
    first = _cycle(home)
    assert first == (THREAD, str(rollout), "rest")
    counts.scandir = counts.connect = 0
    assert _cycle(home) == first
    assert (counts.scandir, counts.connect) == (0, 0)


def test_new_rollout_after_a_miss_is_found_next_cycle(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    assert codex_gather.rollout_path_for(str(home), THREAD) is None
    rollout = _write_rollout(home, "18")
    assert codex_gather.rollout_path_for(str(home), THREAD) == str(rollout)


def test_rotated_rollout_is_walked_again_when_the_old_one_is_gone(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    old = _write_rollout(home, "17")
    assert codex_gather.rollout_path_for(str(home), THREAD) == str(old)
    old.unlink()
    new = _write_rollout(home, "18")
    assert codex_gather.rollout_path_for(str(home), THREAD) == str(new)
    new.unlink()
    assert codex_gather.rollout_path_for(str(home), THREAD) is None


def test_db_write_is_picked_up_next_cycle(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    _write_rollout(home, "18")
    assert _cycle(home)[2] == "rest"
    con = sqlite3.connect(home / "thread_history_1.sqlite")
    con.execute("DELETE FROM thread_turns")
    con.commit()
    con.close()
    assert _cycle(home)[2] == "absent"
    con = sqlite3.connect(home / "state_5.sqlite")
    con.execute("UPDATE threads SET cwd = '/elsewhere'")
    con.commit()
    con.close()
    assert _cycle(home)[0] is None


def test_new_db_version_is_picked_up(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    assert codex_stores.latest_state_db(str(home)).endswith("state_5.sqlite")
    (home / "state_6.sqlite").write_bytes(b"")
    assert codex_stores.latest_state_db(str(home)).endswith("state_6.sqlite")


def test_cache_is_bounded_and_drops_a_vanished_db(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    db = str(home / "state_5.sqlite")
    for i in range(codex_read_cache.MAX_ENTRIES + 20):
        codex_read_cache.remembered_db_read(db, ("k", i), lambda: (i, True))
    assert len(codex_read_cache._db_answers) == codex_read_cache.MAX_ENTRIES
    os.unlink(db)
    codex_read_cache.remembered_db_read(db, ("k", codex_read_cache.MAX_ENTRIES + 19), lambda: (0, True))
    assert (db, ("k", codex_read_cache.MAX_ENTRIES + 19)) not in codex_read_cache._db_answers


def test_failed_read_is_not_remembered(tmp_path: Path) -> None:
    db = tmp_path / "x.sqlite"
    db.write_bytes(b"")
    calls: List[int] = []

    def load():
        calls.append(1)
        return None, False

    codex_read_cache.remembered_db_read(str(db), "q", load)
    codex_read_cache.remembered_db_read(str(db), "q", load)
    assert len(calls) == 2


def test_failed_offset_query_keeps_the_status_but_is_not_remembered(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    db = str(home / "thread_history_1.sqlite")
    con = sqlite3.connect(db)
    con.execute("DROP TABLE thread_history_projection_state")
    con.commit()
    con.close()
    facts = codex_stores.read_codex_record(db, THREAD, lock_live=False)
    assert facts.verdict == "rest"
    assert not codex_read_cache._db_answers
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE thread_history_projection_state (thread_id TEXT, next_rollout_byte_offset INT)")
    con.execute("INSERT INTO thread_history_projection_state VALUES (?, 0)", (THREAD,))
    con.commit()
    con.close()
    assert codex_stores.read_codex_record(db, THREAD, lock_live=False, rollout_size=10**9).verdict == "absent"


def test_second_rollout_for_the_same_thread_wins_like_the_walk(tmp_path: Path, counts: _Counts) -> None:
    home = _make_home(tmp_path)
    first = _write_rollout(home, "17")
    assert codex_gather.rollout_path_for(str(home), THREAD) == str(first)
    same_day = home / "sessions" / "2026" / "11" / "17" / ("rollout-2026-11-17T09-00-00-%s.jsonl" % THREAD)
    same_day.write_text("{}\n")
    assert codex_gather.rollout_path_for(str(home), THREAD) == str(same_day)
    later = _write_rollout(home, "18")
    assert codex_gather.rollout_path_for(str(home), THREAD) == str(later)
    counts.scandir = 0
    assert codex_gather.rollout_path_for(str(home), THREAD) == str(later)
    assert counts.scandir == 0


def test_hit_refreshes_recency(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    db = str(home / "state_5.sqlite")
    codex_read_cache.remembered_db_read(db, "keep", lambda: (1, True))
    for i in range(codex_read_cache.MAX_ENTRIES - 1):
        codex_read_cache.remembered_db_read(db, ("f", i), lambda: (0, True))
    codex_read_cache.remembered_db_read(db, "keep", lambda: (2, True))
    codex_read_cache.remembered_db_read(db, "new", lambda: (0, True))
    assert (db, "keep") in codex_read_cache._db_answers
    assert (db, ("f", 0)) not in codex_read_cache._db_answers
