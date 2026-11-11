
from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.core.account_switch import auto_restart, continue_ready, limit_detect
from src.core.account_switch.limit_rotate import Rotation as RealRotation
from tests.test_account_switch_restart import (  # noqa: F401
    NOW, STOP, Evidence, Manager, Rotation, clear_skip_log, blank_pane, info, run, state,
)

RULE = "─" * 40
EMPTY_PROMPT = f"old output\n{RULE}\n❯ \n{RULE}\n  ? for shortcuts"
TYPED_PROMPT = f"old output\n{RULE}\n❯ half a message\n{RULE}\n  ? for shortcuts"
MENU = (
    "You've hit your session limit · resets 4pm (America/New_York)\n\n"
    "What do you want to do?\n\n"
    "❯ 1. Stop and wait for limit to reset\n"
    "  2. Wait here, then continue automatically at 4:00 PM\n"
    "  3. Switch to usage credits\n\n"
    "Enter to confirm · Esc to cancel\n"
)




def test_the_rate_limit_menu_is_a_pane_stop_with_its_continue_time_as_label():
    assert limit_detect.pane_stop_label(MENU) == "4:00 PM"
    bare = MENU.replace("  2. Wait here, then continue automatically at 4:00 PM\n", "")
    assert limit_detect.pane_stop_label(bare) == limit_detect.MENU_LABEL


@pytest.mark.parametrize("screen", [
    "I hit a limit, so What do you want to do?\n1. Stop and wait for limit to reset\n3. Switch to usage credits",
    "What do you want to do?\n1. Rename the file\n2. Delete it\n3. Switch to usage credits",
    "What do you want to do?\n1. Stop and wait for limit to reset",
    MENU + "\n".join(f"line {i}" for i in range(20)),
    "",
])
def test_prose_or_a_partial_menu_is_not_a_pane_stop(screen):
    assert limit_detect.pane_stop_label(screen) is None




def test_only_an_empty_input_box_counts_as_a_resting_prompt():
    assert continue_ready.shows_empty_prompt(EMPTY_PROMPT)
    assert not continue_ready.shows_empty_prompt(TYPED_PROMPT)
    assert not continue_ready.shows_empty_prompt(MENU)
    assert not continue_ready.shows_empty_prompt(None)


def test_the_pane_must_stay_unchanged_for_the_settle_window():
    reads = iter([EMPTY_PROMPT, EMPTY_PROMPT + "\n(busy)"])
    waited = []

    async def capture():
        return next(reads)

    async def sleep(seconds):
        waited.append(seconds)

    assert not asyncio.run(continue_ready.settled_at_empty_prompt(None, None, capture=capture, sleep=sleep))
    assert waited == [continue_ready.SETTLE_SECONDS]
    same = iter([EMPTY_PROMPT, EMPTY_PROMPT])

    async def steady():
        return next(same)

    assert asyncio.run(continue_ready.settled_at_empty_prompt(None, None, capture=steady, sleep=sleep))


def _rotation(monkeypatch, status, *, gate="ready", hint=None, settled=True):
    real = RealRotation(SimpleNamespace(session_manager=object()), lambda: None)

    async def fake_settled(manager, i, **_):
        return settled

    monkeypatch.setattr(continue_ready, "settled_at_empty_prompt", fake_settled)
    row = SimpleNamespace(activity_status=status, startup_gate=gate, activity_hint=hint)
    return asyncio.run(real.ready_to_continue(row))


def test_ready_is_idle_or_finished_or_a_settled_unknown_and_nothing_else(monkeypatch):
    assert _rotation(monkeypatch, "idle") and _rotation(monkeypatch, "finished_unread")
    assert _rotation(monkeypatch, "unknown")
    assert not _rotation(monkeypatch, "unknown", settled=False)
    assert not _rotation(monkeypatch, "unknown", gate="awaiting_startup_prompt")
    assert not _rotation(monkeypatch, "unknown", hint="shell")
    for status in ("question", "notice", "working", "dead"):
        assert not _rotation(monkeypatch, status)




def _paste(monkeypatch, screen, *, rotation_continue):
    from src.api import one_shot_routes
    from tests import test_one_shot_route as t

    t._screen(monkeypatch, "clear")

    async def capture(manager, i, *, capture=None):
        return continue_ready.shows_empty_prompt(screen)

    monkeypatch.setattr(continue_ready, "at_empty_prompt", capture)
    client, backend = t._client(info=t.FakeInfo(t.STATUS_UNKNOWN, t.GATE_READY, "claude", agent_family="claude"))
    client.app.state.session_manager._info.activity_hint = None
    request = SimpleNamespace(app=client.app)
    try:
        asyncio.run(one_shot_routes.paste_through_gates(
            request, t.CREATED_ID, "continue", idle_only=True, rotation_continue=rotation_continue))
    except HTTPException as exc:
        return exc.detail["code"], backend.pastes
    return None, backend.pastes


def test_the_rotation_paste_takes_an_unknown_pane_at_an_empty_prompt_and_nobody_else_does(monkeypatch):
    assert _paste(monkeypatch, EMPTY_PROMPT, rotation_continue=True) == (None, ["continue"])
    assert _paste(monkeypatch, TYPED_PROMPT, rotation_continue=True) == ("pane_dialog_open", [])
    assert _paste(monkeypatch, EMPTY_PROMPT, rotation_continue=False) == ("pane_dialog_open", [])




def test_the_debt_is_durable_and_one_per_record(state):
    state.owe_continue("rec-1", {"tmux": "t", "epoch": 7, "pid": None})
    assert state.owed("rec-1")["tmux"] == "t" and list(state.owed_records()) == ["rec-1"]
    state.mark_continue_sent("rec-1")
    assert state.owed("rec-1") is None
    state.owe_continue("rec-1", {"tmux": "t", "epoch": 7, "pid": None})
    assert state.owed("rec-1") is None


def test_an_unknown_pane_that_was_not_ready_gets_its_continue_on_a_later_pass_exactly_once(state):
    manager = Manager([info("cloude_a")])
    stuck = Rotation(ready=False)
    run(manager, state, rotation=stuck)
    assert stuck.pasted == [] and state.owed("rec-1") is not None
    ready = Rotation()
    for clock in (200.0, 300.0, 400.0):
        run(manager, state, rotation=ready, clock=clock)
    assert ready.pasted == [("id_cloude_a", "uuid-1")]
    assert [n[0] for n in ready.notices] == ["limit_rotated"] and state.owed("rec-1") is None
    assert len(manager.respawned) == 1


def test_the_debt_is_never_paid_into_another_pane(state):
    manager = Manager([info("cloude_a")])
    run(manager, state, rotation=Rotation(ready=False))
    manager.rows = [info("cloude_a", status="idle")]
    manager.rows[0].session.tmux_created_epoch = 99
    paid = Rotation()
    run(manager, state, rotation=paid, clock=200.0)
    assert paid.pasted == [] and [n[0] for n in paid.notices] == ["limit_failed"] and state.owed("rec-1") is None


def test_a_claude_that_changed_under_the_pane_is_not_typed_into(state):
    manager = Manager([info("cloude_a")])
    run(manager, state, rotation=Rotation(ready=False), evidence=Evidence())
    state.bind_owed_pid("rec-1", 4242)
    manager.rows = [info("cloude_a", status="idle")]
    other = Evidence()

    async def new_pid(_info):
        return 9999

    other.body_pid = new_pid
    paid = Rotation()
    run(manager, state, rotation=paid, evidence=other, clock=200.0)
    assert paid.pasted == [] and [n[0] for n in paid.notices] == ["limit_failed"]


def test_a_paste_that_may_have_landed_is_never_repeated(state):
    manager = Manager([info("cloude_a")])
    run(manager, state, rotation=Rotation(ready=False))

    class Half(Rotation):
        async def paste_continue(self, info, session_uuid):
            raise HTTPException(status_code=409, detail={"code": "paste_not_submitted"})

    manager.rows = [info("cloude_a", status="idle")]
    half = Half()
    run(manager, state, rotation=half, clock=200.0)
    assert state.continue_sent("rec-1") and [n[0] for n in half.notices] == ["limit_failed"]
    again = Rotation()
    run(manager, state, rotation=again, clock=300.0)
    assert again.pasted == []




def test_frozen_sessions_restart_concurrently_each_with_its_own_wait_and_continue(state):
    names = ["cloude_a", "cloude_b", "cloude_c", "cloude_d", "cloude_e"]
    manager = Manager([info(n) for n in names])

    class Slow(Rotation):
        live = peak = 0

        async def wait_ready(self, session_id):
            Slow.live += 1
            Slow.peak = max(Slow.peak, Slow.live)
            await asyncio.sleep(0.05)
            Slow.live -= 1
            return True

    class Many(Evidence):
        async def limit_stop(self, i, **_):
            return STOP.__class__(f"rec-{i.tmux_session}", STOP.timestamp, STOP.resets_at, STOP.rate_limit_type)

    for n in names:
        state.take_baseline({})
    slow = Slow()
    made = run(manager, state, rotation=slow, evidence=Many(blocked=names))
    assert len(made) == auto_restart.MAX_RESTARTS_PER_PASS == 4
    assert Slow.peak == 4 and len(slow.pasted) == 4
    assert {p[0] for p in slow.pasted} == {r.session_id for r in made}
