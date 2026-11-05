
from __future__ import annotations

import os
import tempfile
import time
from contextlib import closing
from pathlib import Path
from typing import Iterator, List, Optional

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_stampreads_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_stampreads_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.session_work_stamp import persist_instance_stamp
from src.core.sessions.lazy_write import LazyWriteConnection

SOCKET = "cloude"
NAME = "cloude_Mac"
EPOCH = 200
HELD = "2026-09-03T10:00:00Z"


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Path]:
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state, 4, "0.0.0").status == "ok"
    path = db_path_for(state)
    with closing(connect(path)) as conn:
        conn.execute(
            "INSERT INTO sessions (session_uuid, origin, tmux_socket, tmux_name, tmux_created_epoch, lifecycle, "
            "project_attribution, last_work_at, created_at, updated_at) "
            "VALUES ('u', 'created', ?, ?, ?, 'running', 'explicit', ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
            (SOCKET, NAME, EPOCH, HELD),
        )
        conn.commit()
    yield path


def stamp(db: Path, *, at: Optional[str], epoch: int = EPOCH) -> List[str]:
    opened: List[str] = []
    read = connect(db)

    def open_writer():
        opened.append("w")
        return connect(db)

    persist_instance_stamp(
        lambda: LazyWriteConnection(read, open_writer, owns_read=True),
        "ses_1", NAME, tmux_socket=SOCKET, tmux_created_epoch=epoch, at=at,
    )
    return opened


def held(db: Path) -> str:
    with closing(connect(db)) as conn:
        return conn.execute("SELECT last_work_at FROM sessions").fetchone()[0]


def test_an_instant_not_newer_than_the_held_one_opens_no_writer(db: Path) -> None:
    assert stamp(db, at=HELD) == []
    assert stamp(db, at="2026-09-03T09:00:00Z") == []
    assert held(db) == HELD


def test_an_unidentified_instance_opens_no_writer(db: Path) -> None:
    assert stamp(db, at="2026-09-04T00:00:00Z", epoch=999) == []
    assert held(db) == HELD


def test_a_newer_instant_still_writes_through_one_writer(db: Path) -> None:
    assert stamp(db, at="2026-09-04T00:00:00Z") == ["w"]
    assert held(db) == "2026-09-04T00:00:00Z"


def test_a_newer_stamp_committed_between_the_plan_and_the_write_wins(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core import session_work_stamp as sws

    newer = "2026-09-05T00:00:00Z"
    real_plan, calls, statements, logged = sws.plan_stamp, [], [], []

    def plan_then_race_once(*args, **kwargs):
        calls.append(1)
        plan = real_plan(*args, **kwargs)
        if len(calls) == 1:
            with closing(connect(db)) as rival:
                rival.execute("UPDATE sessions SET last_work_at = ?", (newer,))
                rival.commit()
        return plan

    class Recorder:

        def debug(self, event: str, **_kw: object) -> None:
            logged.append(event)

        warning = error = info = debug

    def open_writer():
        writer = connect(db)
        writer.set_trace_callback(statements.append)
        return writer

    monkeypatch.setattr(sws, "plan_stamp", plan_then_race_once)
    monkeypatch.setattr(sws, "logger", Recorder())
    started = time.monotonic()
    persist_instance_stamp(
        lambda: LazyWriteConnection(connect(db), open_writer, owns_read=True),
        "ses_1", NAME, tmux_socket=SOCKET, tmux_created_epoch=EPOCH, at="2026-09-04T00:00:00Z",
    )
    assert time.monotonic() - started < 5, "the write must not wait on a lock"
    assert len(calls) == 2, "planned once outside the lock and decided again inside it"
    assert any(q.upper().startswith("BEGIN IMMEDIATE") for q in statements), "the write transaction did start"
    assert not any(q.lstrip().upper().startswith("UPDATE SESSIONS") for q in statements), "the re-decision refused: no UPDATE ran"
    assert "work_stamp_persist_failed" not in logged and "work_stamp_write_failed" not in logged, logged
    assert held(db) == newer, "the rival's newer instant must survive"
