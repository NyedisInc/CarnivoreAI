
from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, List

import pytest

from src.core.attention import codex_gather, codex_stores


def test_version_pick_is_numeric(tmp_path: Path) -> None:
    for name in ("state_9.sqlite", "state_10.sqlite", "state_x.sqlite"):
        (tmp_path / name).write_text("")
    assert codex_stores.latest_state_db(str(tmp_path)) == str(tmp_path / "state_10.sqlite")
    (tmp_path / "thread_history_2.sqlite").write_text("")
    (tmp_path / "thread_history_11.sqlite").write_text("")
    assert codex_stores.latest_history_db(str(tmp_path)) == str(tmp_path / "thread_history_11.sqlite")


def test_one_lsof_for_every_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    locks = tmp_path / "thread-writer-locks"
    locks.mkdir()
    for u in ("aa", "bb", "cc"):
        (locks / f"{u}.lock").write_text("")
    calls: List[List[str]] = []

    def fake_run(argv: List[str], **_: Any) -> Any:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=f"p{os.getpid()}\nn{locks}/bb.lock\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    live = codex_stores.live_writer_lock_uuids(str(tmp_path), ["aa", "bb", "cc", "gone"])
    assert live == {"bb"}
    assert len(calls) == 1


def test_state_db_failure_falls_back_and_is_logged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "state_1.sqlite"
    sqlite3.connect(db).close()
    rollout = tmp_path / "sessions" / "2026" / "01" / "01" / "rollout-1-abc.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text("")
    assert codex_gather.rollout_path_for(str(tmp_path), "abc") == str(rollout)
