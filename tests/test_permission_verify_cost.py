
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from typing import List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pvc_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pvc_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.session_permission_verify import (
    PERMISSION_NOT_CHECKED,
    PERMISSION_TAIL_GRACE_SECONDS,
    PERMISSION_TAIL_RECHECK_SECONDS,
)
from src.core.session_permission_verify_apply import verify_open_permission

HEALTHY_SESSIONS = 6

DIALOG_TAIL = (
    "  Bash command\n"
    "\n"
    "    date +%s\n"
    "\n"
    "  Do you want to proceed?\n"
    "  > 1. Yes\n"
    "    2. No\n"
    "\n"
    "  Esc to cancel . Tab to amend\n"
)


class _FakeTracker:

    def __init__(self, opened: Optional[dict] = None) -> None:
        self.opened = dict(opened or {})
        self.cleared: List[str] = []

    def permission_open_since(self, session_id: str) -> Optional[datetime]:
        return self.opened.get(session_id)

    def clear_permission(self, session_id: str) -> bool:
        if self.opened.pop(session_id, None) is None:
            return False
        self.cleared.append(session_id)
        return True


class _FakeManager:

    def __init__(self, tracker: _FakeTracker) -> None:
        self._activity_tracker = tracker


class _FakeBackend:

    def __init__(self, socket_name: str = "cloude_pytest_permcost") -> None:
        self.socket_name = socket_name


class _CaptureCounter:

    def __init__(self, tail: Optional[str]) -> None:
        self.tail = tail
        self.count = 0

    def install(self, monkeypatch) -> None:
        from src.core import session_startup_gate_ledger as gate_ledger

        counter = self

        def counting(**kwargs):
            counter.count += 1
            return counter.tail

        monkeypatch.setattr(gate_ledger, "capture_pane_tail", counting)


def test_a_healthy_box_spends_no_subprocess_here(monkeypatch):
    counter = _CaptureCounter(DIALOG_TAIL)
    counter.install(monkeypatch)
    tracker = _FakeTracker()
    manager = _FakeManager(tracker)
    now = datetime(2026, 9, 10, 12, 0, 0)

    verdicts = [
        verify_open_permission(
            manager,
            session_id=f"ses_healthy_{i}",
            backend=_FakeBackend(),
            tmux_name=f"cloude_healthy_{i}",
            pane_alive=True,
            now=now,
        )
        for i in range(HEALTHY_SESSIONS)
    ]

    assert counter.count == 0, (
        f"the permission verification spawned {counter.count} capture-pane "
        f"calls across {HEALTHY_SESSIONS} sessions with NO open claim. "
        "Every refusal in this gate is fail-closed and must stay that "
        "way: a session with nothing on record has no claim, so a box "
        "with no dialog open must spend nothing on the listing path."
    )
    assert all(v == PERMISSION_NOT_CHECKED for v in verdicts)


def test_an_open_claim_past_the_grace_window_is_still_verified(monkeypatch):
    counter = _CaptureCounter("nothing here looks like a dialog\n")
    counter.install(monkeypatch)
    now = datetime(2026, 9, 10, 12, 0, 0)
    opened = now - timedelta(seconds=PERMISSION_TAIL_GRACE_SECONDS + 1)
    tracker = _FakeTracker({"ses_stuck": opened})
    manager = _FakeManager(tracker)

    verify_open_permission(
        manager,
        session_id="ses_stuck",
        backend=_FakeBackend(),
        tmux_name="cloude_stuck",
        pane_alive=True,
        now=now,
    )

    assert counter.count == 1, "the first look at a claim is never throttled"
    assert tracker.cleared == ["ses_stuck"], (
        "a claim whose pane shows no dialog must still be cleared - the "
        "throttle bounds the RE-look and may not weaken the verification"
    )


def test_a_claim_whose_dialog_is_still_there_is_not_re_read_every_poll(
    monkeypatch,
):
    counter = _CaptureCounter(DIALOG_TAIL)
    counter.install(monkeypatch)
    start = datetime(2026, 9, 10, 12, 0, 0)
    opened = start - timedelta(seconds=PERMISSION_TAIL_GRACE_SECONDS + 1)
    tracker = _FakeTracker({"ses_open": opened})
    manager = _FakeManager(tracker)

    def poll(at: datetime) -> None:
        verify_open_permission(
            manager,
            session_id="ses_open",
            backend=_FakeBackend(),
            tmux_name="cloude_open",
            pane_alive=True,
            now=at,
        )

    poll(start)
    assert counter.count == 1
    poll(start + timedelta(seconds=5))
    poll(start + timedelta(seconds=10))
    assert counter.count == 1, (
        f"three polls inside the {PERMISSION_TAIL_RECHECK_SECONDS}s "
        f"recheck window cost {counter.count} captures. Re-reading a "
        "dialog that is still on screen buys nothing: if the claim is "
        "real its own claude clears it with a hook, and if it is the "
        "stuck-bit case the FIRST look already cleared it."
    )

    poll(start + timedelta(seconds=PERMISSION_TAIL_RECHECK_SECONDS + 1))
    assert counter.count == 2, (
        "a throttle that never expires is a verification that stopped "
        "happening"
    )


def test_a_new_claim_is_read_immediately_even_right_after_a_check(monkeypatch):
    counter = _CaptureCounter(DIALOG_TAIL)
    counter.install(monkeypatch)
    start = datetime(2026, 9, 10, 12, 0, 0)
    first_claim = start - timedelta(seconds=PERMISSION_TAIL_GRACE_SECONDS + 1)
    tracker = _FakeTracker({"ses_churn": first_claim})
    manager = _FakeManager(tracker)

    def poll(at: datetime) -> None:
        verify_open_permission(
            manager,
            session_id="ses_churn",
            backend=_FakeBackend(),
            tmux_name="cloude_churn",
            pane_alive=True,
            now=at,
        )

    poll(start)
    assert counter.count == 1

    later = start + timedelta(seconds=1)
    tracker.opened["ses_churn"] = later - timedelta(
        seconds=PERMISSION_TAIL_GRACE_SECONDS + 1
    )
    poll(later)

    assert counter.count == 2, (
        "a NEW permission claim was throttled by the previous claim's "
        "reading. The first look at a claim is what catches a flag no "
        "reachable event can retire, and it must never be delayed."
    )


def test_a_refused_read_does_not_start_a_throttle_window(monkeypatch):
    counter = _CaptureCounter(DIALOG_TAIL)
    counter.install(monkeypatch)
    start = datetime(2026, 9, 10, 12, 0, 0)
    opened = start - timedelta(seconds=PERMISSION_TAIL_GRACE_SECONDS + 1)
    tracker = _FakeTracker({"ses_norow": opened})
    manager = _FakeManager(tracker)

    verify_open_permission(
        manager,
        session_id="ses_norow",
        backend=_FakeBackend(),
        tmux_name="cloude_norow",
        pane_alive=None,
        now=start,
    )
    assert counter.count == 0

    verify_open_permission(
        manager,
        session_id="ses_norow",
        backend=_FakeBackend(),
        tmux_name="cloude_norow",
        pane_alive=True,
        now=start + timedelta(seconds=1),
    )
    assert counter.count == 1, (
        "a refused read started a throttle window, so the claim's first "
        "real look was skipped"
    )
