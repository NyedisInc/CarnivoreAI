
from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime, timedelta

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_sg_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_sg_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.session_startup_gate import (
    ALL_STARTUP_GATES,
    GATE_AWAITING,
    GATE_READY,
    GATE_UNKNOWN,
    STARTUP_HOOK_GRACE_SECONDS,
    STARTUP_TAIL_LINES,
    detect_startup_prompt,
    resolve_startup_gate,
    should_capture_tail,
)
from src.core.session_startup_gate_ledger import StartupGateLedger


TRUST_PROMPT_TAIL = """
 Accessing workspace:

 /private/tmp/cc-probe/workdir

 Quick safety check: Is this a project you created or one you trust? (Like your own code, a
 well-known open source project, or work from your team). If not, take a moment to review what's in
 this folder first.

 Claude Code'll be able to read, edit, and execute files here.

 Security guide

 ❯ No, exit
   Yes, I trust this folder

 Enter to confirm · Esc to cancel
"""

STEADY_STATE_TAIL = """
 ▐▛███▛█   Claude Code v2.1.263
▝▜██████▀  Opus 5 (1M context) · Claude Max
  ▝▝ ▝▝    /private/tmp/cc-probe/workdir

❯
  jsugamele@mac-mini-m4:/private/tmp/cc-probe/workdir
  ⏵⏵ auto mode on (shift+tab to cycle) · ← for agents
"""

PAST_GRACE = float(STARTUP_HOOK_GRACE_SECONDS + 5)




def test_matcher_finds_the_real_trust_dialog():
    assert detect_startup_prompt(TRUST_PROMPT_TAIL) is True


def test_matcher_negative_control_steady_state_claude():
    assert detect_startup_prompt(STEADY_STATE_TAIL) is False


def test_matcher_finds_the_oauth_login_screen():
    tail = "Browser didn't open? Use the url below:\nhttps://claude.com/cai/oauth/authorize?code=1"
    assert detect_startup_prompt(tail) is True


def test_matcher_separates_did_not_look_from_looked_and_found_nothing():
    assert detect_startup_prompt(None) is None
    assert detect_startup_prompt("") is False




def test_alive_pane_no_hook_past_threshold_with_prompt_is_awaiting():
    assert (
        resolve_startup_gate(
            pane_alive=True,
            first_hook_at=None,
            instance_age_seconds=PAST_GRACE,
            tail=TRUST_PROMPT_TAIL,
        )
        == GATE_AWAITING
    )


def test_alive_pane_no_hook_past_threshold_without_prompt_is_ready():
    assert (
        resolve_startup_gate(
            pane_alive=True,
            first_hook_at=None,
            instance_age_seconds=PAST_GRACE,
            tail=STEADY_STATE_TAIL,
        )
        == GATE_READY
    )




def test_hook_seen_is_ready():
    assert (
        resolve_startup_gate(
            pane_alive=True,
            first_hook_at=datetime(2026, 9, 8, 15, 0, 0),
            instance_age_seconds=PAST_GRACE,
            tail=None,
        )
        == GATE_READY
    )


def test_hook_seen_beats_prompt_text_lingering_in_scrollback():
    assert (
        resolve_startup_gate(
            pane_alive=True,
            first_hook_at=datetime(2026, 9, 8, 15, 0, 0),
            instance_age_seconds=PAST_GRACE,
            tail=TRUST_PROMPT_TAIL,
        )
        == GATE_READY
    )


def test_a_young_session_showing_the_prompt_is_unknown_not_awaiting():
    assert (
        resolve_startup_gate(
            pane_alive=True,
            first_hook_at=None,
            instance_age_seconds=1.0,
            tail=TRUST_PROMPT_TAIL,
        )
        == GATE_UNKNOWN
    )


def test_a_gone_process_is_not_waiting_for_a_keypress():
    assert (
        resolve_startup_gate(
            pane_alive=False,
            first_hook_at=None,
            instance_age_seconds=PAST_GRACE,
            tail=TRUST_PROMPT_TAIL,
        )
        == GATE_READY
    )




def test_unknown_pane_liveness_is_unknown():
    assert (
        resolve_startup_gate(
            pane_alive=None,
            first_hook_at=None,
            instance_age_seconds=PAST_GRACE,
            tail=TRUST_PROMPT_TAIL,
        )
        == GATE_UNKNOWN
    )


def test_undatable_instance_is_unknown():
    assert (
        resolve_startup_gate(
            pane_alive=True,
            first_hook_at=None,
            instance_age_seconds=None,
            tail=TRUST_PROMPT_TAIL,
        )
        == GATE_UNKNOWN
    )


def test_uncaptured_tail_is_unknown():
    assert (
        resolve_startup_gate(
            pane_alive=True,
            first_hook_at=None,
            instance_age_seconds=PAST_GRACE,
            tail=None,
        )
        == GATE_UNKNOWN
    )


def test_every_verdict_is_in_the_vocabulary():
    for alive in (True, False, None):
        for hook in (None, datetime(2026, 9, 8)):
            for age in (None, 1.0, PAST_GRACE):
                for tail in (None, "", TRUST_PROMPT_TAIL, STEADY_STATE_TAIL):
                    verdict = resolve_startup_gate(
                        pane_alive=alive,
                        first_hook_at=hook,
                        instance_age_seconds=age,
                        tail=tail,
                    )
                    assert verdict in ALL_STARTUP_GATES




def test_capture_is_skipped_for_a_session_that_has_fired_a_hook():
    assert (
        should_capture_tail(
            pane_alive=True,
            first_hook_at=datetime(2026, 9, 8),
            instance_age_seconds=PAST_GRACE,
        )
        is False
    )


def test_capture_runs_only_for_a_live_hookless_pane_past_the_window():
    assert (
        should_capture_tail(
            pane_alive=True,
            first_hook_at=None,
            instance_age_seconds=PAST_GRACE,
        )
        is True
    )
    assert (
        should_capture_tail(
            pane_alive=None,
            first_hook_at=None,
            instance_age_seconds=PAST_GRACE,
        )
        is False
    )
    assert (
        should_capture_tail(
            pane_alive=True, first_hook_at=None, instance_age_seconds=1.0
        )
        is False
    )
    assert (
        should_capture_tail(
            pane_alive=True, first_hook_at=None, instance_age_seconds=None
        )
        is False
    )


def test_a_duplicate_hook_does_not_move_the_first_hook_time():
    ledger = StartupGateLedger()
    first = datetime(2026, 9, 8, 15, 0, 0)
    ledger.record_hook("cloude_a", now=first)
    ledger.record_hook("cloude_a", now=first + timedelta(minutes=10))
    assert ledger.first_hook_at("cloude_a") == first


def test_a_hook_makes_the_gate_ready_through_the_ledger():
    ledger = StartupGateLedger()
    ledger.record_hook("cloude_a", now=datetime(2026, 9, 8, 15, 0, 0))
    assert (
        resolve_startup_gate(
            pane_alive=True,
            first_hook_at=ledger.first_hook_at("cloude_a"),
            instance_age_seconds=PAST_GRACE,
            tail=TRUST_PROMPT_TAIL,
        )
        == GATE_READY
    )


def test_a_live_respawn_resets_the_instance():
    ledger = StartupGateLedger()
    ledger.record_hook("cloude_a", epoch=7, now=datetime(2026, 9, 8))
    ledger.observe_instance("cloude_a", epoch=7, pane_pid=100)
    assert ledger.first_hook_at("cloude_a") is not None

    ledger.observe_instance("cloude_a", epoch=7, pane_pid=200)
    assert ledger.first_hook_at("cloude_a") is None


def test_a_reused_tmux_name_with_a_new_epoch_resets_the_instance():
    ledger = StartupGateLedger()
    ledger.record_hook("cloude_a", epoch=7, now=datetime(2026, 9, 8))
    ledger.observe_instance("cloude_a", epoch=7, pane_pid=100)
    ledger.observe_instance("cloude_a", epoch=9, pane_pid=100)
    assert ledger.first_hook_at("cloude_a") is None


def test_an_unmeasured_pid_is_adopted_not_treated_as_a_change():
    ledger = StartupGateLedger()
    ledger.record_hook("cloude_a", now=datetime(2026, 9, 8))
    for _ in range(5):
        ledger.observe_instance("cloude_a", epoch=None, pane_pid=None)
    assert ledger.first_hook_at("cloude_a") is not None


def test_observe_instance_on_an_unknown_name_is_a_no_op():
    ledger = StartupGateLedger()
    ledger.observe_instance("never_seen", epoch=1, pane_pid=2)
    assert ledger.first_hook_at("never_seen") is None


def test_forget_drops_the_instance():
    ledger = StartupGateLedger()
    ledger.record_hook("cloude_a", now=datetime(2026, 9, 8))
    ledger.forget("cloude_a")
    assert ledger.first_hook_at("cloude_a") is None
    ledger.forget("cloude_a")


def test_a_missing_tmux_name_never_records():
    ledger = StartupGateLedger()
    ledger.record_hook(None, now=datetime(2026, 9, 8))
    assert ledger.first_hook_at(None) is None



from pathlib import Path  # noqa: E402

from src.core.session_manager import SessionManager  # noqa: E402
from src.core.session_status import LIVENESS_LIVE, LIVENESS_UNKNOWN  # noqa: E402
from src.models import Session, SessionStatus  # noqa: E402


class _StubSettings:

    def __init__(self, root: Path):
        self._root = root
        (root / "logs").mkdir(parents=True, exist_ok=True)

    def get_pinned_themes_path(self) -> Path:
        return self._root / "pinned_themes.json"

    def get_unread_state_path(self) -> Path:
        return self._root / "unread_state.json"

    @property
    def log_directory(self) -> str:
        return str(self._root / "logs")

    def get_session_metadata_path(self) -> Path:
        return self._root / "logs" / "session_metadata.json"


class _FakeBackend:

    def __init__(self, tmux_session: str):
        self.tmux_session = tmux_session
        self.socket_name = "cloude-test-never-real"

    def is_alive(self) -> bool:
        return True


def _manager(monkeypatch, tmp_path: Path) -> SessionManager:
    monkeypatch.setattr(
        "src.core.session_manager.settings", _StubSettings(tmp_path)
    )
    return SessionManager()


def _register(mgr: SessionManager, sid: str, name: str, tmp_path: Path) -> None:
    mgr._registry.sessions[sid] = Session(
        id=sid,
        pty_pid=None,
        working_dir=str(tmp_path),
        status=SessionStatus.RUNNING,
        tmux_session=name,
    )
    mgr._registry.backends[sid] = _FakeBackend(name)
    mgr._registry.subscribers.setdefault(sid, [])


def _stub_tail(monkeypatch, text):
    monkeypatch.setattr(
        "src.core.session_manager.capture_pane_tail",
        lambda **kwargs: text,
    )


def test_manager_reports_awaiting_and_raises_no_toast(
    monkeypatch, tmp_path
):
    mgr = _manager(monkeypatch, tmp_path)
    _register(mgr, "ses1", "cloude_proj", tmp_path)
    _stub_tail(monkeypatch, TRUST_PROMPT_TAIL)

    old_epoch = int(time.time()) - 600
    row = {"created_at_epoch": old_epoch, "pid": 4321}

    verdicts = []
    for _ in range(3):
        verdicts.append(
            mgr._startup_gate_for(
                session_id="ses1",
                backend=mgr._registry.backends["ses1"],
                tmux_name="cloude_proj",
                row=row,
                liveness=LIVENESS_LIVE,
            )
        )

    assert verdicts == [GATE_AWAITING, GATE_AWAITING, GATE_AWAITING]
    assert mgr._toast_inbox.get("ses1") == []


def test_manager_reports_ready_once_a_sign_of_life_lands(monkeypatch, tmp_path):
    mgr = _manager(monkeypatch, tmp_path)
    _register(mgr, "ses1", "cloude_proj", tmp_path)
    _stub_tail(monkeypatch, TRUST_PROMPT_TAIL)

    mgr._startup_gate_ledger.record_hook("cloude_proj", epoch=None)

    row = {
        "created_at_epoch": int(time.time()) - 600,
        "pid": 4321,
    }
    assert (
        mgr._startup_gate_for(
            session_id="ses1",
            backend=mgr._registry.backends["ses1"],
            tmux_name="cloude_proj",
            row=row,
            liveness=LIVENESS_LIVE,
        )
        == GATE_READY
    )


def test_manager_refuses_to_guess_when_liveness_is_unknown(
    monkeypatch, tmp_path
):
    mgr = _manager(monkeypatch, tmp_path)
    _register(mgr, "ses1", "cloude_proj", tmp_path)
    _stub_tail(monkeypatch, TRUST_PROMPT_TAIL)

    row = {
        "created_at_epoch": int(time.time()) - 600,
        "pid": 4321,
    }
    assert (
        mgr._startup_gate_for(
            session_id="ses1",
            backend=mgr._registry.backends["ses1"],
            tmux_name="cloude_proj",
            row=row,
            liveness=LIVENESS_UNKNOWN,
        )
        == GATE_UNKNOWN
    )
    assert mgr._toast_inbox.get("ses1") == []


def test_manager_never_captures_a_tail_for_a_session_with_a_sign_of_life(
    monkeypatch, tmp_path
):
    mgr = _manager(monkeypatch, tmp_path)
    _register(mgr, "ses1", "cloude_proj", tmp_path)

    calls = []

    def _explode(**kwargs):
        calls.append(kwargs)
        return TRUST_PROMPT_TAIL

    monkeypatch.setattr(
        "src.core.session_manager.capture_pane_tail", _explode
    )
    mgr._startup_gate_ledger.record_hook("cloude_proj", epoch=None)

    row = {
        "created_at_epoch": int(time.time()) - 600,
        "pid": 4321,
    }
    mgr._startup_gate_for(
        session_id="ses1",
        backend=mgr._registry.backends["ses1"],
        tmux_name="cloude_proj",
        row=row,
        liveness=LIVENESS_LIVE,
    )
    gate_calls = [c for c in calls if c.get("lines") == STARTUP_TAIL_LINES]
    assert gate_calls == []


def test_manager_forgets_the_gate_when_the_session_is_wiped(
    monkeypatch, tmp_path
):
    mgr = _manager(monkeypatch, tmp_path)
    _register(mgr, "ses1", "cloude_proj", tmp_path)
    mgr._startup_gate_ledger.record_hook("cloude_proj", epoch=None)
    assert mgr._startup_gate_ledger.first_hook_at("cloude_proj") is not None

    mgr._wipe_session_state("ses1")
    assert mgr._startup_gate_ledger.first_hook_at("cloude_proj") is None
