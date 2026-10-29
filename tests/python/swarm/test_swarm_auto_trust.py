
from __future__ import annotations

import asyncio
import os
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.approvals.extract import extract_dialog
from src.core.companies import store as companies
from src.core.db import connect, db_path_for
from src.core.swarm import auto_trust, body, body_create, delivery, store
from tests.python.swarm.test_swarm_card_settle_and_retry import BASE, world  # noqa: F401
from tests.python.swarm.test_swarm_company_hq import _db, _decide, _suggest, env  # noqa: F401

SCREENS = Path(__file__).resolve().parents[2] / "fixtures" / "startup_screens"
YES = "Yes, I trust this folder"


@pytest.fixture
def rig(world, monkeypatch):  # noqa: F811
    folder = world.tmp / "made"
    folder.mkdir()
    state = SimpleNamespace(dialog=None, answers=[], gate="awaiting_startup_prompt", clock=datetime.now(timezone.utc), stale=False)

    class Info:
        session = SimpleNamespace(id="ses_1", working_dir=str(folder))
        agent_family, tmux_session = "claude", None
        startup_gate = property(lambda self: state.gate)

    info = Info()

    def observation_for(_sid):
        return SimpleNamespace(evidence=SimpleNamespace(dialog=state.dialog), stale=state.stale, observed_at=state.clock)

    app_state = SimpleNamespace(attention_watcher=SimpleNamespace(observation_for=observation_for), session_manager=None)
    with closing(connect(db_path_for(world.tmp), create=False)) as conn:
        conn.execute("UPDATE swarm_agents SET repo_dir = ? WHERE id = ?", (str(folder), world.boss["id"]))
        wake_id = store.open_wake(conn, world.boss["id"], reason="owner_message", mode="fresh", authority="owner")
        agent = store.get_agent(conn, world.boss["id"])

    async def live_info(_state, _agent):
        return info

    async def send_answer(_state, session_id, fingerprint, label):
        state.answers.append((session_id, fingerprint, label))

    monkeypatch.setattr(body, "live_info", live_info)
    monkeypatch.setattr(delivery, "_send_answer", send_answer)
    for table in (delivery._trust_posted, delivery._trust_card_at, delivery._trust_auto_tries, delivery._trust_auto_at):
        table.clear()
    monkeypatch.setattr(delivery, "AUTO_TRUST_CONFIRM_S", 0.3)
    monkeypatch.setattr(delivery, "AUTO_TRUST_POLL_S", 0.02)
    state.folder, state.info, state.app_state, state.agent, state.wake_id, state.world = folder, info, app_state, agent, wake_id, world
    state.created = lambda: _alpha_row(world, folder)
    state.sees = lambda text: setattr(state, "dialog", extract_dialog((SCREENS / text).read_text(), "claude"))
    state.cards = lambda prefix: [i for i in world.client.get(f"{BASE}/lists/{world.boss['thread_key']}").json()["items"]
                                  if (i.get("swarm_ref") or "").startswith(prefix)]
    state.tick = lambda: asyncio.run(delivery._maybe_dialog_card(app_state, agent, wake_id, info))
    yield state
    for table in (delivery._trust_posted, delivery._trust_card_at, delivery._trust_auto_tries, delivery._trust_auto_at):
        table.clear()


def _alpha_row(world, folder):
    with closing(connect(db_path_for(world.tmp), create=False)) as conn:
        store.create_agent(conn, slug="alpha", rank="alpha", job="j", display_name="Alpha", repo_dir=str(folder), effort="high")


def test_a_carnivore_made_folder_is_trusted_with_no_card(rig):
    rig.created()
    rig.sees("trust_dialog.txt")
    assert rig.dialog is not None and rig.dialog.kind == "folder_trust"
    rig.tick()
    assert rig.answers == [("ses_1", rig.dialog.fingerprint, YES)]
    assert rig.cards(delivery.TRUST_PREFIX) == []
    rig.tick()
    assert len(rig.answers) == 1 and rig.cards(delivery.TRUST_PREFIX) == []
    rig.clock += timedelta(seconds=2)
    rig.tick()
    assert len(rig.answers) == 1 and len(rig.cards(delivery.TRUST_PREFIX)) == 1


def test_only_the_exact_trust_dialog_in_the_exact_folder_is_auto_answered(rig):
    rig.created()
    for screen in ("chrome_extension.txt", "external_imports.txt"):
        rig.sees(screen)
        assert rig.dialog is not None
        rig.tick()
    assert rig.answers == []
    rig.sees("trust_dialog.txt")
    rig.info.session.working_dir = str(rig.folder / "sub")
    rig.tick()
    rig.info.session.working_dir = str(rig.folder.parent)
    delivery._trust_posted.clear()
    rig.tick()
    assert rig.answers == []
    rig.info.session.working_dir = str(rig.folder)
    rig.info.agent_family = "codex"
    delivery._trust_posted.clear()
    rig.tick()
    assert rig.answers == []


def test_a_folder_carnivore_did_not_create_gets_one_open_card_through_a_spurious_clear_read(rig):
    rig.sees("trust_dialog.txt")
    rig.tick()
    assert rig.answers == []
    (card,) = rig.cards(delivery.TRUST_PREFIX)
    assert card["state"] == "open"
    rig.dialog, rig.gate = None, "unknown"
    rig.clock += timedelta(seconds=2)
    assert asyncio.run(delivery.close_gone_trust_cards(rig.app_state, rig.agent, rig.wake_id)) is False
    rig.sees("trust_dialog.txt")
    rig.tick()
    rig.dialog, rig.gate, rig.stale = None, "ready", True
    assert asyncio.run(delivery.close_gone_trust_cards(rig.app_state, rig.agent, rig.wake_id)) is False
    rig.sees("trust_dialog.txt")
    rig.stale = False
    rig.tick()
    (card,) = rig.cards(delivery.TRUST_PREFIX)
    assert card["state"] == "open"
    delivery._trust_posted.clear()
    delivery._trust_card_at.clear()
    rig.tick()
    assert [c["id"] for c in rig.cards(delivery.TRUST_PREFIX)] == [card["id"]]
    rig.dialog, rig.gate = None, "ready"
    rig.clock += timedelta(seconds=2)
    assert asyncio.run(delivery.close_gone_trust_cards(rig.app_state, rig.agent, rig.wake_id)) is True
    assert rig.cards(delivery.TRUST_PREFIX) == []
    (closed,) = rig.cards("closed:trust:")
    assert closed["id"] == card["id"] and closed["state"] == "done"


def test_a_closed_card_is_not_posted_again_in_the_same_wake(rig):
    rig.sees("trust_dialog.txt")
    rig.tick()
    (card,) = rig.cards(delivery.TRUST_PREFIX)
    rig.dialog, rig.gate = None, "ready"
    rig.clock += timedelta(seconds=2)
    asyncio.run(delivery.close_gone_trust_cards(rig.app_state, rig.agent, rig.wake_id))
    rig.sees("trust_dialog.txt")
    rig.tick()
    assert rig.cards(delivery.TRUST_PREFIX) == [] and [c["id"] for c in rig.cards("closed:trust:")] == [card["id"]]
    delivery.forget_wake(rig.wake_id)
    assert not delivery._trust_posted


def test_the_made_by_carnivore_predicate_follows_what_a_creation_path_made(env):  # noqa: F811
    own = env.root / "Own Repo"
    own.mkdir()
    (own / "notes.md").write_text("mine\n")
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        existing = body_create.register_project(conn, str(own), "Own Repo")
        companies.assign_project(conn, existing["id"], env.acme["id"])
    _suggest(env, "acmeboss", kind="project", name="Own Repo", reason="adopt the existing one")
    _suggest(env, "acmeboss", kind="project", name="Billing API", reason="the roadmap needs billing")
    refs = [c[2] for c in env.port.cards if c[2].startswith("suggest:")]
    assert len(refs) == 2
    for ref in refs:
        _decide(env, ref, "approve")
    made = env.root / "Billing API"
    assert made.is_dir()
    assert _db(env, lambda c: auto_trust.made_by_carnivore(c, str(made)))
    assert not _db(env, lambda c: auto_trust.made_by_carnivore(c, str(own)))
    assert _db(env, lambda c: c.execute("SELECT made_project_id FROM swarm_suggestions WHERE name = 'Own Repo'").fetchone()[0]) is None
    assert not _db(env, lambda c: auto_trust.made_by_carnivore(c, str(made / "sub")))
    assert not _db(env, lambda c: auto_trust.made_by_carnivore(c, str(env.root)))
    link = env.root.parent / "link"
    os.symlink(made, link)
    assert _db(env, lambda c: auto_trust.made_by_carnivore(c, str(link)))


ASK_TRUST_SCREEN = """ ▐▛███▛█   Claude Code v2.1.285
▝▜██████▀  rig-model[1m] · API Usage Billing
 ▝▝   ▝▝   /…/T/tmprigwkkkk/cw
────────────────────────────────────────────────────────────
 ☐ Trust
│ Quick safety check: Is this a project you created or one you trust? Trust this folder?
❯ 1. Yes, I trust this folder
  2. No, exit
  3. Type something.
────────────────────────────────────────────────────────────
  4. Chat about this
Enter to select · ↑/↓ to navigate · Esc to cancel
"""


def test_an_agents_own_askuserquestion_is_not_auto_answered(rig):
    rig.created()
    rig.dialog = extract_dialog(ASK_TRUST_SCREEN, "claude")
    assert rig.dialog is not None and len(rig.dialog.rows) > 2
    rig.tick()
    assert rig.answers == []


def test_the_trust_screen_after_a_gate_pass_or_a_recorded_kickoff_is_not_auto_answered(rig):
    rig.created()
    rig.sees("trust_dialog.txt")
    rig.gate = "ready"
    rig.tick()
    assert rig.answers == []
    rig.gate = "awaiting_startup_prompt"
    delivery.record(rig.agent["id"], "owner", "wake_prompt", f"wake:{rig.wake_id}", "huddle:msg:1")
    delivery._trust_posted.clear()
    rig.tick()
    assert rig.answers == []


def test_a_card_from_before_a_restart_closes_once_the_owner_answered_in_the_terminal(rig):
    rig.sees("trust_dialog.txt")
    rig.tick()
    (card,) = rig.cards(delivery.TRUST_PREFIX)
    delivery._trust_posted.clear()
    delivery._trust_card_at.clear()
    rig.tick()
    assert [c["id"] for c in rig.cards(delivery.TRUST_PREFIX)] == [card["id"]] and delivery._trust_card_at
    rig.dialog, rig.gate = None, "ready"
    rig.clock += timedelta(seconds=2)
    assert asyncio.run(delivery.close_gone_trust_cards(rig.app_state, rig.agent, rig.wake_id)) is True
    assert rig.cards(delivery.TRUST_PREFIX) == []


def test_a_made_folder_that_became_a_symlink_is_no_longer_made_by_carnivore(rig):
    rig.created()
    rig.sees("trust_dialog.txt")
    with closing(connect(db_path_for(rig.world.tmp), create=False)) as conn:
        assert auto_trust.made_by_carnivore(conn, str(rig.folder))
        assert auto_trust.may_auto_answer(conn, rig.agent, {"id": rig.wake_id}, rig.info, rig.dialog)
        owners_repo = rig.world.tmp / "owners-repo"
        owners_repo.mkdir()
        rig.folder.rmdir()
        os.symlink(owners_repo, rig.folder)
        assert not auto_trust.made_by_carnivore(conn, str(rig.folder))
        assert not auto_trust.made_by_carnivore(conn, str(owners_repo))
        agent = dict(rig.agent, repo_dir=str(rig.folder))
        assert not auto_trust.may_auto_answer(conn, agent, {"id": rig.wake_id}, rig.info, rig.dialog)


def _repaint_after(rig, monkeypatch, seconds):
    sent = []

    reading = {"dialog": rig.dialog, "at": datetime.now(timezone.utc) - timedelta(seconds=5)}

    async def send_answer(_state, session_id, fingerprint, label):
        sent.append(datetime.now(timezone.utc))
        rig.answers.append((session_id, fingerprint, label))
        reading.update(dialog=rig.dialog, at=datetime.now(timezone.utc) + timedelta(seconds=0.5))

    async def tick_sessions(_ids):
        gone = seconds is not None and sent and datetime.now(timezone.utc) - sent[0] > timedelta(seconds=seconds)
        reading.update(dialog=None if gone else rig.dialog, at=datetime.now(timezone.utc) + timedelta(seconds=0.5))
        return 0

    def observation_for(_sid):
        return SimpleNamespace(evidence=SimpleNamespace(dialog=reading["dialog"]), stale=False, observed_at=reading["at"])

    monkeypatch.setattr(delivery, "_send_answer", send_answer)
    rig.app_state.attention_watcher = SimpleNamespace(observation_for=observation_for, tick_sessions=tick_sessions)


def test_an_auto_answer_that_takes_posts_no_card_even_when_the_first_reading_still_shows_the_dialog(rig, monkeypatch):
    rig.created()
    rig.sees("trust_dialog.txt")
    _repaint_after(rig, monkeypatch, 0.1)
    rig.tick()
    assert len(rig.answers) == 1 and rig.cards(delivery.TRUST_PREFIX) == [] and rig.cards("closed:trust:") == []
    rig.tick()
    assert len(rig.answers) == 1 and rig.cards(delivery.TRUST_PREFIX) == []


def test_an_auto_answer_whose_dialog_stays_past_the_window_gets_exactly_one_card(rig, monkeypatch):
    rig.created()
    rig.sees("trust_dialog.txt")
    _repaint_after(rig, monkeypatch, None)
    rig.tick()
    assert len(rig.answers) == 1
    assert len(rig.cards(delivery.TRUST_PREFIX)) == 1
    rig.tick()
    assert len(rig.answers) == 1 and len(rig.cards(delivery.TRUST_PREFIX)) == 1


def test_a_wake_ended_through_the_unwind_path_closes_its_open_trust_card(rig):
    rig.sees("trust_dialog.txt")
    rig.tick()
    assert len(rig.cards(delivery.TRUST_PREFIX)) == 1
    asyncio.run(body._unwind(rig.agent["id"], rig.wake_id))
    assert rig.cards(delivery.TRUST_PREFIX) == []
    (closed,) = rig.cards("closed:trust:")
    assert closed["state"] == "done"
    assert not delivery._trust_posted and not delivery._trust_card_at


def test_a_second_cancel_during_the_unwind_still_closes_the_trust_card(rig):
    rig.sees("trust_dialog.txt")
    rig.tick()
    assert len(rig.cards(delivery.TRUST_PREFIX)) == 1

    async def cancel_the_unwind():
        task = asyncio.create_task(body._unwind(rig.agent["id"], rig.wake_id))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        rest = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        assert rest
        await asyncio.wait_for(asyncio.gather(*rest), 5)

    asyncio.run(cancel_the_unwind())
    assert rig.cards(delivery.TRUST_PREFIX) == []
    (closed,) = rig.cards("closed:trust:")
    assert closed["state"] == "done"
