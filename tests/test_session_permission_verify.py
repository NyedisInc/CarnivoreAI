
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from tests.attention_claim_helpers import open_claims
from src.core.session_activity import (
    EVENT_PERMISSION_REQUEST,
    EVENT_STOP,
    EVENT_USER_PROMPT_SUBMIT,
    SessionActivityTracker,
)
from src.core.session_permission_verify import (
    PERMISSION_CLEARED_NO_DIALOG,
    PERMISSION_CLEARED_PANE_DEAD,
    PERMISSION_KEPT_DIALOG,
    PERMISSION_KEPT_UNREADABLE,
    PERMISSION_NOT_CHECKED,
    PERMISSION_TAIL_GRACE_SECONDS,
    detect_permission_dialog,
    resolve_permission_check,
    should_capture_permission_tail,
)
from src.core.session_status import STATUS_IDLE, STATUS_QUESTION
from src.core.sessions.registry import SessionRegistry
from src.core.session_view_clears import clear_view_state


_RULE = "\u2500" * 120
_DOTTED = "\u254c" * 120

BASH_DIALOG = "\n".join(
    [
        "  \u23bf  $ date +%s",
        "",
        _RULE,
        " Bash command",
        "",
        "   date +%s",
        "   Print current Unix timestamp",
        "",
        " Ask rule Bash overrides auto mode for this command.",
        " /permissions to let auto mode decide",
        "",
        " Do you want to proceed?",
        " \u276f 1. Yes",
        "   2. No",
        "",
        " Esc to cancel \u00b7 Tab to amend",
    ]
)

WRITE_DIALOG = "\n".join(
    [
        "\u276f use the Write tool to create note2.txt containing the word hello",
        "",
        "\u23fa Write(note2.txt)",
        "",
        _RULE,
        " Create file",
        " note2.txt",
        _DOTTED,
        "  1 hello",
        _DOTTED,
        " Do you want to create note2.txt?",
        " \u276f 1. Yes",
        "   2. No",
        "",
        " Esc to cancel \u00b7 Tab to amend",
    ]
)

IDLE_PANE = "\n".join(
    [
        _RULE,
        "\u276f",
        _RULE,
        "  contributor@hostb:/private/tmp/claude-1000/junstone\u2026",
        "  \u23f5\u23f5 auto mode on (shift+tab to cycle) \u00b7 \u2190 for agents",
        "                                                              /rc",
    ]
)

STUCK_LIVE_PANE = "\n".join(
    [
        "some earlier output from the agent",
        "",
        "                                                                                    new task? /clear to save 100.0k tokens",
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 Image Tool \u2500",
        "\u276f\xa0continue with the next step",
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
        "  user@host:~/project git:(main) [Opus 5]",
        "  \u23f5\u23f5 bypass permissions on (shift+tab to cycle) \xb7 \u2190 for agents",
    ]
)

T0 = datetime(2026, 1, 1, 0, 0, 0)




@pytest.mark.parametrize(
    "tail,label",
    [(BASH_DIALOG, "bash"), (WRITE_DIALOG, "write")],
    ids=["bash-dialog", "write-dialog"],
)
def test_a_real_permission_dialog_is_detected(tail: str, label: str) -> None:
    assert detect_permission_dialog(tail) is True, label


@pytest.mark.parametrize(
    "tail,label",
    [(IDLE_PANE, "idle"), (STUCK_LIVE_PANE, "stuck-live")],
    ids=["idle-pane", "stuck-live-pane"],
)
def test_a_pane_with_no_dialog_is_not_detected(tail: str, label: str) -> None:
    assert detect_permission_dialog(tail) is False, label


def test_the_question_line_alone_is_enough_for_an_unseen_wording() -> None:
    assert detect_permission_dialog(
        " Do you want to make this edit to app.py?"
    ) is True


def test_the_phrase_mid_sentence_does_not_match() -> None:
    prose = (
        "I can refactor this next. Do you want to proceed with the "
        "migration first, or should I write the tests?"
    )
    assert detect_permission_dialog(prose) is False


def test_no_text_is_not_the_same_answer_as_no_dialog() -> None:
    assert detect_permission_dialog(None) is None
    assert detect_permission_dialog("") is False




def test_a_fresh_flag_inside_the_grace_window_is_never_captured() -> None:
    assert should_capture_permission_tail(
        pane_alive=True,
        permission_open=True,
        opened_at=T0,
        now=T0 + timedelta(seconds=PERMISSION_TAIL_GRACE_SECONDS - 1),
    ) is False


def test_a_flag_past_the_grace_window_is_captured() -> None:
    assert should_capture_permission_tail(
        pane_alive=True,
        permission_open=True,
        opened_at=T0,
        now=T0 + timedelta(seconds=PERMISSION_TAIL_GRACE_SECONDS),
    ) is True


@pytest.mark.parametrize(
    "kwargs,label",
    [
        ({"pane_alive": None}, "pane unmeasured"),
        ({"pane_alive": False}, "pane dead"),
        ({"permission_open": False}, "no open flag"),
        ({"opened_at": None}, "undatable claim"),
    ],
)
def test_the_gate_refuses_everything_it_cannot_stand_behind(
    kwargs: dict, label: str
) -> None:
    base = dict(
        pane_alive=True,
        permission_open=True,
        opened_at=T0,
        now=T0 + timedelta(seconds=600),
    )
    base.update(kwargs)
    assert should_capture_permission_tail(**base) is False, label




def test_marker_present_keeps_the_flag() -> None:
    assert (
        resolve_permission_check(captured=True, tail=BASH_DIALOG)
        == PERMISSION_KEPT_DIALOG
    )


def test_tail_read_and_no_marker_clears_the_flag() -> None:
    assert (
        resolve_permission_check(captured=True, tail=STUCK_LIVE_PANE)
        == PERMISSION_CLEARED_NO_DIALOG
    )


def test_an_unreadable_tail_keeps_the_flag() -> None:
    assert (
        resolve_permission_check(captured=True, tail=None)
        == PERMISSION_KEPT_UNREADABLE
    )


def test_a_refused_capture_says_nothing_about_the_flag() -> None:
    assert (
        resolve_permission_check(captured=False, tail=None)
        == PERMISSION_NOT_CHECKED
    )




def test_clearing_drops_the_stamp_with_the_flag() -> None:
    t = SessionActivityTracker()
    open_claims(t, "s1", permission=True, at=T0)
    assert t.clear_permission("s1") is True
    assert t.permission_open_since("s1") is None
    assert t.clear_permission("s1") is False


def test_a_cleared_claim_is_never_captured_for_again() -> None:
    t = SessionActivityTracker()
    open_claims(t, "s1", permission=True, at=T0)
    t.clear_permission("s1")
    assert should_capture_permission_tail(
        pane_alive=True,
        permission_open=t.permission_open_since("s1") is not None,
        opened_at=t.permission_open_since("s1"),
        now=T0 + timedelta(hours=1),
    ) is False


def test_a_fresh_claim_gets_its_own_grace_window() -> None:
    t = SessionActivityTracker()
    later = T0 + timedelta(seconds=120)
    open_claims(t, "s1", permission=True, at=later)
    assert t.permission_open_since("s1") == later
    assert should_capture_permission_tail(
        pane_alive=True,
        permission_open=True,
        opened_at=t.permission_open_since("s1"),
        now=later + timedelta(seconds=1),
    ) is False


def test_clear_permission_on_an_unknown_session_is_a_no_op() -> None:
    assert SessionActivityTracker().clear_permission("nope") is False
    assert SessionActivityTracker().permission_open_since("nope") is None




class _FakeBackend:

    def __init__(self, tmux_session: str) -> None:
        self.tmux_session = tmux_session


class _FakeUnreadStore:

    def __init__(self) -> None:
        self.cleared: list[tuple[str, object]] = []

    def clear(self, tmux_name: str, epoch: object, row_id: object = None) -> None:
        self.cleared.append((tmux_name, epoch))


class _FakeManager:

    def __init__(self, tracker: SessionActivityTracker) -> None:
        self._registry = SessionRegistry(log_cap=lambda: 1000)
        self._registry.backends["ses_1"] = _FakeBackend(
            "cloude_Image_Tool"
        )
        self._activity_tracker = tracker
        self._unread_store = _FakeUnreadStore()

    def _unread_epoch(self, tmux_name: str) -> str:
        return "epoch-1"


def test_a_view_clears_an_open_permission() -> None:
    tracker = SessionActivityTracker()
    open_claims(tracker, "ses_1", permission=True, at=T0)
    mgr = _FakeManager(tracker)

    assert clear_view_state(mgr, session_id="ses_1") is True
    assert tracker.permission_open_since("ses_1") is None
    assert tracker.permission_open_since("ses_1") is None


def test_a_view_is_idempotent() -> None:
    tracker = SessionActivityTracker()
    open_claims(tracker, "ses_1", permission=True, at=T0)
    mgr = _FakeManager(tracker)

    clear_view_state(mgr, session_id="ses_1")
    first = tracker.permission_open_since("ses_1")
    clear_view_state(mgr, session_id="ses_1")
    assert tracker.permission_open_since("ses_1") == first
    assert len(mgr._unread_store.cleared) == 2


def test_a_view_by_tmux_name_clears_the_permission_too() -> None:
    tracker = SessionActivityTracker()
    open_claims(tracker, "ses_1", permission=True, at=T0)
    mgr = _FakeManager(tracker)

    assert clear_view_state(mgr, tmux_name="cloude_Image_Tool") is True
    assert tracker.permission_open_since("ses_1") is None


def test_a_view_still_clears_the_notice_and_the_unread_flag() -> None:
    tracker = SessionActivityTracker()
    signal = open_claims(
        tracker, "ses_1", permission=True, notice=True, at=T0
    )
    mgr = _FakeManager(tracker)

    clear_view_state(mgr, session_id="ses_1")

    assert signal.notice_open is False
    assert signal.permission_open is False
    assert mgr._unread_store.cleared == [
        ("cloude_Image_Tool", "epoch-1")
    ]




class _CountingBackend(_FakeBackend):

    def __init__(self, tmux_session: str, socket_name: str = "cloude") -> None:
        super().__init__(tmux_session)
        self.socket_name = socket_name


def _seam_manager(tracker: SessionActivityTracker) -> _FakeManager:
    mgr = _FakeManager(tracker)
    mgr._registry.backends["ses_1"] = _CountingBackend(
        "cloude_Image_Tool"
    )
    return mgr


def _run_seam(monkeypatch, tracker, tail, *, now, calls: list) -> str:
    from src.core import session_permission_verify_apply as apply_mod
    from src.core import session_startup_gate_ledger as ledger

    def fake_capture(*, socket: str, name: str, lines: int):
        calls.append((socket, name, lines))
        return tail

    monkeypatch.setattr(ledger, "capture_pane_tail", fake_capture)
    return apply_mod.verify_open_permission(
        _seam_manager(tracker),
        session_id="ses_1",
        backend=_CountingBackend("cloude_Image_Tool"),
        tmux_name="cloude_Image_Tool",
        pane_alive=True,
        now=now,
    )


PAST_GRACE = T0 + timedelta(seconds=PERMISSION_TAIL_GRACE_SECONDS + 5)


def test_the_seam_does_not_capture_inside_the_grace_window(monkeypatch) -> None:
    tracker = SessionActivityTracker()
    open_claims(tracker, "ses_1", permission=True, at=T0)
    calls: list = []
    verdict = _run_seam(
        monkeypatch, tracker, IDLE_PANE,
        now=T0 + timedelta(seconds=1), calls=calls,
    )
    assert verdict == PERMISSION_NOT_CHECKED
    assert calls == []
    assert tracker.permission_open_since("ses_1") == T0


def test_the_seam_does_not_capture_when_no_permission_is_open(
    monkeypatch,
) -> None:
    calls: list = []
    verdict = _run_seam(
        monkeypatch, SessionActivityTracker(), IDLE_PANE,
        now=PAST_GRACE, calls=calls,
    )
    assert verdict == PERMISSION_NOT_CHECKED
    assert calls == []


def test_the_seam_clears_a_flag_with_no_dialog_on_the_pane(
    monkeypatch,
) -> None:
    tracker = SessionActivityTracker()
    open_claims(tracker, "ses_1", permission=True, at=T0)
    calls: list = []
    verdict = _run_seam(
        monkeypatch, tracker, STUCK_LIVE_PANE, now=PAST_GRACE, calls=calls,
    )
    assert verdict == PERMISSION_CLEARED_NO_DIALOG
    assert len(calls) == 1
    assert tracker.permission_open_since("ses_1") is None
    assert tracker.permission_open_since("ses_1") is None


def test_the_seam_captures_once_per_poll_then_stops(monkeypatch) -> None:
    tracker = SessionActivityTracker()
    open_claims(tracker, "ses_1", permission=True, at=T0)
    calls: list = []
    _run_seam(monkeypatch, tracker, STUCK_LIVE_PANE, now=PAST_GRACE, calls=calls)
    _run_seam(monkeypatch, tracker, STUCK_LIVE_PANE, now=PAST_GRACE, calls=calls)
    assert len(calls) == 1


def test_the_seam_keeps_a_flag_with_a_dialog_on_the_pane(monkeypatch) -> None:
    tracker = SessionActivityTracker()
    open_claims(tracker, "ses_1", permission=True, at=T0)
    calls: list = []
    verdict = _run_seam(
        monkeypatch, tracker, BASH_DIALOG, now=PAST_GRACE, calls=calls,
    )
    assert verdict == PERMISSION_KEPT_DIALOG
    assert tracker.permission_open_since("ses_1") == T0
    assert tracker.permission_open_since("ses_1") is not None


def test_the_seam_keeps_a_flag_it_could_not_read_the_pane_for(
    monkeypatch,
) -> None:
    tracker = SessionActivityTracker()
    open_claims(tracker, "ses_1", permission=True, at=T0)
    calls: list = []
    verdict = _run_seam(
        monkeypatch, tracker, None, now=PAST_GRACE, calls=calls,
    )
    assert verdict == PERMISSION_KEPT_UNREADABLE
    assert tracker.permission_open_since("ses_1") == T0
    assert tracker.permission_open_since("ses_1") is not None
    _run_seam(monkeypatch, tracker, None, now=PAST_GRACE, calls=calls)
    assert len(calls) == 2


def test_the_seam_never_invents_a_permission(monkeypatch) -> None:
    tracker = SessionActivityTracker()
    calls: list = []
    verdict = _run_seam(
        monkeypatch, tracker, BASH_DIALOG, now=PAST_GRACE, calls=calls,
    )
    assert verdict == PERMISSION_NOT_CHECKED
    assert tracker.permission_open_since("ses_1") is None
    assert tracker.permission_open_since("ses_1") is None


def test_the_seam_refuses_an_unmeasured_pane(monkeypatch) -> None:
    from src.core import session_permission_verify_apply as apply_mod
    from src.core import session_startup_gate_ledger as ledger

    calls: list = []
    monkeypatch.setattr(
        ledger, "capture_pane_tail",
        lambda **kw: calls.append(kw) or IDLE_PANE,
    )
    tracker = SessionActivityTracker()
    open_claims(tracker, "ses_1", permission=True, at=T0)
    assert apply_mod.verify_open_permission(
        _seam_manager(tracker),
        session_id="ses_1",
        backend=_CountingBackend("cloude_Image_Tool"),
        tmux_name="cloude_Image_Tool",
        pane_alive=None,
        now=PAST_GRACE,
    ) == PERMISSION_NOT_CHECKED
    assert calls == []
    assert tracker.permission_open_since("ses_1") == T0


def test_the_seam_clears_a_measured_dead_pane_with_no_capture(monkeypatch) -> None:
    from src.core import session_permission_verify_apply as apply_mod
    from src.core import session_startup_gate_ledger as ledger

    calls: list = []
    monkeypatch.setattr(
        ledger, "capture_pane_tail",
        lambda **kw: calls.append(kw) or IDLE_PANE,
    )
    tracker = SessionActivityTracker()
    open_claims(tracker, "ses_1", permission=True, at=T0)
    assert apply_mod.verify_open_permission(
        _seam_manager(tracker),
        session_id="ses_1",
        backend=_CountingBackend("cloude_Image_Tool"),
        tmux_name="cloude_Image_Tool",
        pane_alive=False,
        now=PAST_GRACE,
    ) == PERMISSION_CLEARED_PANE_DEAD
    assert calls == [], "a dead pane must never be captured - there is nothing to read"
    assert tracker.permission_open_since("ses_1") is None


def test_the_seam_never_raises_when_the_capture_blows_up(monkeypatch) -> None:
    from src.core import session_permission_verify_apply as apply_mod
    from src.core import session_startup_gate_ledger as ledger

    def boom(**kwargs):
        raise OSError("tmux went away")

    monkeypatch.setattr(ledger, "capture_pane_tail", boom)
    tracker = SessionActivityTracker()
    open_claims(tracker, "ses_1", permission=True, at=T0)
    assert apply_mod.verify_open_permission(
        _seam_manager(tracker),
        session_id="ses_1",
        backend=_CountingBackend("cloude_Image_Tool"),
        tmux_name="cloude_Image_Tool",
        pane_alive=True,
        now=PAST_GRACE,
    ) == PERMISSION_NOT_CHECKED
    assert tracker.permission_open_since("ses_1") == T0
