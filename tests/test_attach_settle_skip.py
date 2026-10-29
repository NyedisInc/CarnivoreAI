
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ass_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ass_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.api import attach_settle
from src.api.attach_settle import (
    NO_RESIZE_ATTEMPTED,
    REASON_CHANGED,
    REASON_CONFIRMED_UNCHANGED,
    REASON_NO_CLIENT_GEOMETRY,
    REASON_RESIZE_FAILED,
    REASON_UNMEASURED,
    ResizeOutcome,
    SETTLE_SECONDS,
    SettleVerdict,
    decide_settle,
    read_pane_geometry,
    settle_if_needed,
)
from src.api.resize_negotiation import apply_negotiated_resize
from src.core.tmux_backend import TmuxBackend
from tests.socket_guard import TEST_SOCKET_NAME

requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not on PATH"
)




def test_a_measured_matching_geometry_is_the_only_thing_that_skips():
    verdict = decide_settle((100, 40), ResizeOutcome((100, 40), False, False))
    assert verdict == SettleVerdict(False, REASON_CONFIRMED_UNCHANGED)


def test_a_measured_different_geometry_still_settles():
    verdict = decide_settle((80, 24), ResizeOutcome((100, 40), True, False))
    assert verdict.settle is True
    assert verdict.reason == REASON_CHANGED


def test_an_unmeasured_geometry_settles_and_is_not_read_as_unchanged():
    verdict = decide_settle(None, ResizeOutcome((100, 40), True, False))
    assert verdict.settle is True
    assert verdict.reason == REASON_UNMEASURED


def test_a_failed_resize_settles_even_when_the_reading_matched():
    verdict = decide_settle((100, 40), ResizeOutcome((100, 40), True, True))
    assert verdict.settle is True
    assert verdict.reason == REASON_RESIZE_FAILED


def test_no_client_geometry_settles_which_is_the_fallback_branch():
    verdict = decide_settle(None, NO_RESIZE_ATTEMPTED)
    assert verdict.settle is True
    assert verdict.reason == REASON_NO_CLIENT_GEOMETRY


def test_an_issued_resize_settles_even_if_the_pre_read_matched_the_target():
    verdict = decide_settle((100, 40), ResizeOutcome((100, 40), True, False))
    assert verdict.settle is True
    assert verdict.reason == REASON_CHANGED




def test_the_skip_verdict_takes_no_pause_at_all(monkeypatch):
    slept = []

    async def record(seconds):
        slept.append(seconds)

    monkeypatch.setattr(attach_settle.asyncio, "sleep", record)
    asyncio.run(settle_if_needed(SettleVerdict(False, REASON_CONFIRMED_UNCHANGED)))
    assert slept == []


def test_the_settle_verdict_pauses_for_the_unchanged_duration(monkeypatch):
    slept = []

    async def record(seconds):
        slept.append(seconds)

    monkeypatch.setattr(attach_settle.asyncio, "sleep", record)
    asyncio.run(settle_if_needed(SettleVerdict(True, REASON_CHANGED)))
    assert slept == [SETTLE_SECONDS]
    assert SETTLE_SECONDS == 0.15




def test_a_backend_without_the_probe_reads_as_unmeasured():
    class NoProbe:
        pass

    assert asyncio.run(read_pane_geometry(NoProbe())) is None
    assert asyncio.run(read_pane_geometry(None)) is None


def test_a_probe_that_raises_reads_as_unmeasured_not_as_zero():
    class Raises:
        async def pane_geometry(self):
            raise RuntimeError("tmux went away")

    assert asyncio.run(read_pane_geometry(Raises())) is None


def test_a_probe_answering_nonsense_reads_as_unmeasured():
    class Nonsense:
        async def pane_geometry(self):
            return "not a pair"

    assert asyncio.run(read_pane_geometry(Nonsense())) is None




def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-L", TEST_SOCKET_NAME, *args],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture()
def live_pane(tmp_path):
    name = f"cloude_as_{uuid.uuid4().hex[:8]}"
    result = _tmux(
        "new-session", "-d",
        "-s", name,
        "-c", str(tmp_path),
        "-x", "111", "-y", "37",
    )
    assert result.returncode == 0, f"tmux new-session failed: {result.stderr}"
    _tmux("set-option", "-t", name, "window-size", "manual")
    backend = TmuxBackend(
        session_id=name,
        working_dir=tmp_path,
        socket_name=TEST_SOCKET_NAME,
        session_name=name,
    )
    try:
        yield backend, name
    finally:
        _tmux("kill-session", "-t", name)


@requires_tmux
def test_a_real_pane_reports_its_real_geometry(live_pane):
    backend, _ = live_pane
    assert asyncio.run(backend.pane_geometry()) == (111, 37)


@requires_tmux
def test_a_real_pane_that_moved_is_reported_moved(live_pane):
    backend, name = live_pane
    _tmux("resize-window", "-t", name, "-x", "90", "-y", "30")
    measured = asyncio.run(backend.pane_geometry())
    assert measured == (90, 30)
    verdict = decide_settle(measured, ResizeOutcome((111, 37), True, False))
    assert verdict.settle is True


@requires_tmux
def test_a_real_backend_whose_pane_is_gone_refuses_and_still_settles(live_pane):
    backend, name = live_pane
    assert asyncio.run(backend.pane_geometry()) == (111, 37)

    killed = _tmux("kill-session", "-t", name)
    assert killed.returncode == 0, killed.stderr

    measured = asyncio.run(read_pane_geometry(backend))
    assert measured is None, "a dead pane must refuse, not report a size"

    verdict = decide_settle(measured, ResizeOutcome((111, 37), True, False))
    assert verdict == SettleVerdict(True, REASON_UNMEASURED)




class _RecordingManager:

    def __init__(self):
        self.resizes = []

    def resize_terminal(self, cols, rows, session_id=None):
        self.resizes.append((cols, rows, session_id))


class _NoBroadcast:
    async def broadcast_to_session(self, session_id, message):
        return None


def test_a_measured_match_issues_no_resize_and_reports_the_target():
    manager = _RecordingManager()
    outcome = asyncio.run(apply_negotiated_resize(
        manager, "ses_x", object(), 100, 40, _NoBroadcast(),
        known_pane_size=(100, 40),
    ))
    assert manager.resizes == []
    assert outcome == ResizeOutcome(target=(100, 40), issued=False, failed=False)
    assert decide_settle((100, 40), outcome).settle is False


def test_an_unmeasured_pane_still_issues_the_resize_exactly_as_before():
    manager = _RecordingManager()
    outcome = asyncio.run(apply_negotiated_resize(
        manager, "ses_x", object(), 100, 40, _NoBroadcast(),
        known_pane_size=None,
    ))
    assert manager.resizes == [(100, 40, "ses_x")]
    assert outcome.issued is True
    assert decide_settle(None, outcome).settle is True


def test_a_second_smaller_client_makes_the_target_the_negotiated_minimum():
    manager = _RecordingManager()
    big, small = object(), object()
    asyncio.run(apply_negotiated_resize(
        manager, "ses_x", big, 200, 60, _NoBroadcast()))
    outcome = asyncio.run(apply_negotiated_resize(
        manager, "ses_x", small, 100, 40, _NoBroadcast()))
    assert outcome.target == (100, 40)

    outcome = asyncio.run(apply_negotiated_resize(
        manager, "ses_x", big, 200, 60, _NoBroadcast(),
        known_pane_size=(100, 40),
    ))
    assert outcome == ResizeOutcome(target=(100, 40), issued=False, failed=False)
    assert decide_settle((100, 40), outcome).settle is False


def test_a_resize_that_raises_is_reported_failed_and_settles():
    class Exploding:
        def resize_terminal(self, cols, rows, session_id=None):
            raise RuntimeError("tmux refused")

    outcome = asyncio.run(apply_negotiated_resize(
        Exploding(), "ses_x", object(), 100, 40, _NoBroadcast(),
        known_pane_size=(80, 24),
    ))
    assert outcome.failed is True
    assert decide_settle((80, 24), outcome) == SettleVerdict(
        True, REASON_RESIZE_FAILED
    )
