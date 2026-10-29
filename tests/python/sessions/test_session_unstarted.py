
import json
import os
from pathlib import Path

import pytest

from src.core.attention.record_identity import read_lstarts
from src.core.attention_history import store as history
from src.core.claude_config import profile_roots
from src.core.claude_config.transcript_roots import reset_transcript_roots_cache_for_tests
from src.core.session_resume_target import ResumeTarget, resume_extra_args
from src.core.sessions.session_unstarted import downgrade_if_unstarted, row_has_recorded_work

UUID = "d66e9f08-1111-4222-8333-444455556666"
TMUX = "carnivore_Real"


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CARNIVORE_ACCOUNTS_DIR", str(tmp_path / "accts"))
    prof = tmp_path / "accts" / "0123456789ab-work-relay"
    (prof / "sessions").mkdir(parents=True)
    (prof / "projects" / "-x-proj").mkdir(parents=True)
    (tmp_path / ".claude" / "projects" / "-other").mkdir(parents=True)
    cfg = tmp_path / "config.json"
    cfg.write_text("{}")
    monkeypatch.setattr(profile_roots, "_default_config_path", lambda: cfg)
    reset_transcript_roots_cache_for_tests()
    lstart = (read_lstarts([os.getpid()]) or {}).get(os.getpid())
    assert lstart, "ps must answer for our own pid"

    def record(proc_start=lstart):
        body = {"pid": os.getpid(), "sessionId": UUID, "status": "idle", "tmux": TMUX + ":@1.%1", "cwd": "/x/proj"}
        if proc_start is not None:
            body["procStart"] = proc_start
        (prof / "sessions" / ("%d.json" % os.getpid())).write_text(json.dumps(body))

    record()
    yield SimpleWorld(prof, tmp_path, record)
    reset_transcript_roots_cache_for_tests()


class SimpleWorld:
    def __init__(self, prof, home, record):
        self.prof, self.home, self.record = prof, home, record


def _target():
    return ResumeTarget(outcome="resumed", claude_session_uuid=UUID)


def _run(**kw):
    out = downgrade_if_unstarted(_target(), TMUX, "/x/proj", **kw)
    return out, " ".join(resume_extra_args(out) or [])


def test_true_never_started_session_restarts_fresh(world) -> None:
    out, argv = _run(recorded_work=False)
    assert out.outcome == "none_recorded" and out.claude_session_uuid is None and "--resume" not in argv


def test_transcript_in_a_relay_profiles_real_projects_dir_keeps_resume(world) -> None:
    (world.prof / "projects" / "-x-proj" / (UUID + ".jsonl")).write_text('{"type":"user"}\n')
    out, argv = _run(recorded_work=False)
    assert out.outcome == "resumed" and UUID in argv


def test_transcript_in_the_default_root_keeps_resume(world) -> None:
    (world.home / ".claude" / "projects" / "-other" / (UUID + ".jsonl")).write_text('{"type":"user"}\n')
    assert _run(recorded_work=False)[0].outcome == "resumed"


@pytest.mark.parametrize("proc_start", ["Mon Jan  1 00:00:00 2001", None])
def test_a_reused_pid_or_a_record_with_no_procstart_does_not_count(world, proc_start) -> None:
    world.record(proc_start)
    assert _run(recorded_work=False)[0].outcome == "resumed"


def test_recorded_turns_with_a_missing_transcript_stay_refused(world) -> None:
    assert _run(recorded_work=True)[0].outcome == "resumed"
    assert _run()[0].outcome == "resumed"


def test_row_work_signal_reads_last_work_at_and_attention_history(tmp_path) -> None:
    assert row_has_recorded_work("2026-10-17T00:00:00+00:00", "u1", tmp_path) is True
    assert row_has_recorded_work(None, None, tmp_path) is True
    assert row_has_recorded_work(None, "u1", tmp_path) is False
    store = history.AttentionHistoryStore(tmp_path / history.DB_NAME)
    from datetime import datetime, timezone

    store.record("u1", history.KIND_BUSY, datetime.now(timezone.utc))
    assert row_has_recorded_work(None, "u1", tmp_path) is True
    assert row_has_recorded_work(None, "u2", tmp_path) is False


def test_codex_rows_keep_today_behavior(world) -> None:
    t = ResumeTarget(outcome="resumed", claude_session_uuid=UUID, family="codex")
    assert downgrade_if_unstarted(t, TMUX, "/x/proj", recorded_work=False).outcome == "resumed"
