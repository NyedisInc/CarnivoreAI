
from datetime import datetime, timezone
from types import SimpleNamespace

from src.core.attention.beast_hold import BeastHold
from src.core.attention.display import to_display
from src.core.attention.evidence import REASON_PERMISSION, STATE_BUSY, STATE_NEEDS_USER, TIER_PANE, AttentionVerdict
from src.core.attention.ledger import AttentionLedger
from src.core.session_status import STATUS_QUESTION

T0 = datetime(2026, 11, 5, tzinfo=timezone.utc)


class Rig:

    def __init__(self, handled: bool) -> None:
        self.now, self.handled, self.toasts, self.ledger = 0.0, handled, 0, AttentionLedger()
        self.hold = BeastHold(lambda _sid, _obs: self.handled, clock=lambda: self.now, hold_seconds=8.0)
        self.target = SimpleNamespace(key="cloude_a:1", session_id="ses_1")

    def tick(self, dialog: bool = True) -> str:
        state = STATE_NEEDS_USER if dialog else STATE_BUSY
        verdict = AttentionVerdict(state, REASON_PERMISSION if dialog else "tool", TIER_PANE)
        obs = SimpleNamespace(verdict=verdict, evidence=SimpleNamespace(dialog=SimpleNamespace(fingerprint="f1") if dialog else None))
        verdict = self.hold.mask(self.target, obs)
        edge = self.ledger.observe(self.target.key, verdict, T0.replace(second=int(self.now) % 60), last_append_at=None)
        self.toasts += int(edge is not None and edge.state == STATE_NEEDS_USER)
        return to_display(verdict, unread=False, tmux_status="running")


def test_handled_question_is_silent_until_answered():
    rig = Rig(handled=True)
    rig.tick(dialog=False)
    for second in range(0, 6):
        rig.now = second
        assert rig.tick() != STATUS_QUESTION
    rig.now = 6
    rig.tick(dialog=False)
    assert rig.toasts == 0


def test_late_answer_alerts_exactly_once():
    rig = Rig(handled=True)
    rig.tick(dialog=False)
    for second in range(0, 20):
        rig.now = second
        light = rig.tick()
    assert (rig.toasts, light) == (1, STATUS_QUESTION)


def test_beast_switched_off_mid_hold_alerts_at_once():
    rig = Rig(handled=True)
    rig.tick(dialog=False)
    rig.now = 3
    assert rig.tick() != STATUS_QUESTION
    rig.handled, rig.now = False, 4
    assert rig.tick() == STATUS_QUESTION and rig.toasts == 1


def test_unhandled_question_alerts_immediately():
    rig = Rig(handled=False)
    rig.tick(dialog=False)
    assert rig.tick() == STATUS_QUESTION and rig.toasts == 1
