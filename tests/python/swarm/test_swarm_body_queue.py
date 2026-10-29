
from __future__ import annotations

import asyncio
import os
import tempfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pb_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pb_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.auto_sleep import swarm_rule
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.swarm import body, delivery, store
from src.core.swarm.body_create import BodyIdentity
from src.cplugs.huddle import held, swarm_tell, sending


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path, raising=True)
    assert ensure_db_migrated(tmp_path).status == "ok"
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        conn.execute(
            "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, working_dir, "
            "title, origin, lifecycle, created_at, updated_at) VALUES ('uuid-loki', 'cloude', 'cloude_loki', 1788821572, "
            "'/tmp/pk', 't', 'created', 'stopped', '2026-03-01T00:00:00Z', '2026-09-08T00:00:00Z')")
        row_id = conn.execute("SELECT id FROM sessions WHERE session_uuid = 'uuid-loki'").fetchone()[0]
        alpha = store.create_agent(conn, slug="alpha", rank="alpha", job="j", display_name="Alpha", repo_dir="/tmp/pk", effort="max")
        loki = store.create_agent(conn, slug="loki", rank="feature", job="swap models", display_name="Loki",
                                  repo_dir="/tmp/pk-loki", effort="high", parent_id=alpha["id"])
        store.set_session_row(conn, loki["id"], row_id)
    return SimpleNamespace(state_dir=tmp_path, agent_id=loki["id"], row_id=row_id)


def _open_wakes(env) -> int:
    with closing(connect(db_path_for(env.state_dir), create=False)) as conn:
        return conn.execute("SELECT COUNT(*) FROM swarm_wakes WHERE ended_at IS NULL").fetchone()[0]


def _stub_start(monkeypatch, env, calls):
    async def fake_start(app_state, agent, mode):
        calls.append(mode)
        await asyncio.sleep(0.05)
        return BodyIdentity("ses_new", env.row_id, "uuid-loki", "cloude_loki", 1788821999)

    monkeypatch.setattr(body, "_start", fake_start)
    monkeypatch.setattr(delivery, "send_wake_prompt", lambda *a, **k: None)


def test_two_wakes_race_into_one_open_wake(env, monkeypatch):
    calls = []
    _stub_start(monkeypatch, env, calls)

    async def go():
        return await asyncio.gather(
            body.wake(object(), env.agent_id, "owner_message", "owner", owner_message_ref="huddle:msg:1"),
            body.wake(object(), env.agent_id, "crosstalk", "data"))

    first, second = asyncio.run(go())
    assert sorted([first.started, second.started]) == [False, True]
    assert first.wake_id == second.wake_id and calls == ["fresh"] and _open_wakes(env) == 1
    with closing(connect(db_path_for(env.state_dir), create=False)) as conn:
        assert store.get_agent(conn, env.agent_id)["state"] == "awake"


def test_failed_start_unwinds_to_asleep_and_leaves_no_open_wake(env, monkeypatch):
    async def boom(app_state, agent, mode):
        raise body.body_create.CreateRefused("no folder")

    monkeypatch.setattr(body, "_start", boom)
    with pytest.raises(body.BodyError):
        asyncio.run(body.wake(object(), env.agent_id, "manual", "data"))
    assert _open_wakes(env) == 0
    with closing(connect(db_path_for(env.state_dir), create=False)) as conn:
        assert store.get_agent(conn, env.agent_id)["state"] == "asleep"


def test_agent_waking_holds_a_tell_for_a_fresh_pane(monkeypatch):
    monkeypatch.setattr(held, "_store_row", lambda ctx, entry: None)
    waking = SimpleNamespace(is_waking=lambda key: True)
    ctx = SimpleNamespace(swarm=waking, settings={}, notify=lambda *a, **k: None)
    gone = HTTPException(status_code=409, detail={"code": "pane_not_an_agent"})
    assert "agent_waking" in held.BUSY_CODES
    refusal = swarm_tell.as_waking(ctx, "agent:3", gone)
    assert refusal.detail["code"] == "agent_waking"
    assert swarm_tell.as_waking(ctx, "12", gone) is gone
    ctx.swarm = SimpleNamespace(is_waking=lambda key: False)
    assert swarm_tell.as_waking(ctx, "agent:3", gone) is gone

    async def go():
        out = sending.held_or_refused(ctx, lambda f: f(), "agent:3", "Loki", [{"id": "ses_1", "label": "Loki"}], "ses_1",
                                      "agent", swarm_tell.as_waking(SimpleNamespace(swarm=waking), "agent:3", gone))
        held.reset()
        return out

    assert asyncio.run(go())["status"] == "held"


def test_waking_window_and_codes():
    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    started = (now - timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    old = (now - timedelta(seconds=delivery.WAKING_WINDOW_S + 5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert delivery.is_waking({"state": "waking"}, None, now=now)
    assert delivery.is_waking({"state": "awake"}, {"started_at": started}, now=now)
    assert not delivery.is_waking({"state": "awake"}, {"started_at": old}, now=now)
    assert delivery.classify("session_gone", waking=True) == delivery.AGENT_WAKING
    assert delivery.classify("session_gone", waking=False) == "session_gone"
    assert delivery.classify("pane_dialog_open", waking=True) == "pane_dialog_open"


def test_refused_paste_leaves_no_authority_row_and_a_taken_one_stays(env, monkeypatch):
    info = SimpleNamespace(tmux_session=None, session=SimpleNamespace(id="ses_new"), startup_gate="ready")
    monkeypatch.setattr(body, "live_info", lambda app_state, agent: _async(info))
    attempts = []

    async def paste(request, session_id, text, **kw):
        attempts.append(text)
        if len(attempts) == 1:
            raise HTTPException(status_code=409, detail={"code": "pane_not_an_agent"})
        return SimpleNamespace(submitted=True)

    import src.api.one_shot_routes as one_shot

    monkeypatch.setattr(one_shot, "paste_through_gates", paste)
    with closing(connect(db_path_for(env.state_dir), create=False)) as conn:
        store.cas_state(conn, env.agent_id, "asleep", "awake")
        conn.execute("INSERT INTO swarm_wakes (agent_id, started_at, reason, mode, authority) VALUES (?, ?, 'manual', 'fresh', 'data')",
                     (env.agent_id, (datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")))

    def rows():
        with closing(connect(db_path_for(env.state_dir), create=False)) as conn:
            return store.list_deliveries(conn, env.agent_id)

    first = asyncio.run(delivery._attempt(object(), env.agent_id, "hi", "owner_chat", "owner", None, "huddle:msg:7"))
    assert first == ("retry", "agent_waking") and rows() == []
    second = asyncio.run(delivery._attempt(object(), env.agent_id, "hi", "owner_chat", "owner", None, "huddle:msg:7"))
    assert second == ("delivered", None)
    kept = rows()
    assert len(kept) == 1 and kept[0]["authority"] == "owner" and kept[0]["owner_message_ref"] == "huddle:msg:7"


async def _async(value):
    return value


def test_sleep_closes_the_wake_and_ends_asleep(env, monkeypatch):
    import src.api.session_sleep_routes as sleep_routes

    async def fake_sleep(app_state, uuid, **kw):
        assert uuid == "uuid-loki" and kw == {"fresh_ok": True}
        return SimpleNamespace(status="asleep", detail="")

    async def alive(app_state, agent):
        return False

    monkeypatch.setattr(sleep_routes, "sleep_by_uuid", fake_sleep)
    monkeypatch.setattr(body, "detect_death", alive)
    _stub_start(monkeypatch, env, [])

    async def go():
        await body.wake(object(), env.agent_id, "manual", "data")
        return await body.sleep(object(), env.agent_id, "auto_sleep")

    result = asyncio.run(go())
    assert result.state == "asleep" and _open_wakes(env) == 0
    with closing(connect(db_path_for(env.state_dir), create=False)) as conn:
        assert store.get_agent(conn, env.agent_id)["state"] == "asleep"
        assert conn.execute("SELECT end_reason FROM swarm_wakes").fetchone()[0] == "auto_sleep"


def test_swarm_auto_sleep_rule_reads_membership_and_pending(env):
    with closing(connect(db_path_for(env.state_dir), create=False)) as conn:
        store.cas_state(conn, env.agent_id, "asleep", "awake")
    members = swarm_rule.read_members(db_path_for(env.state_dir))
    member = members.by_row[env.row_id]
    assert member.agent_id == env.agent_id and member.tmux_name == "cloude_loki"
    assert swarm_rule.pending_reason(member, members) is None
    members.busy_keys.add("uuid-loki")
    assert "crosstalk" in swarm_rule.pending_reason(member, members)
    members.busy_keys.clear()
    members.parents_with_children.add(env.agent_id)
    assert "child" in swarm_rule.pending_reason(member, members)


def test_wake_of_a_moved_away_projects_agent_names_the_move_not_the_load(env, monkeypatch):
    monkeypatch.setattr(body, "caps_refusal", lambda *a, **k: "system is pegged, try later")
    monkeypatch.setattr(body.project_home, "moved_away_for",
                        lambda conn, root: {"display_name": "Sc-a", "moved_to_label": "studio"})
    with pytest.raises(body.BodyError) as err:
        asyncio.run(body.wake(object(), env.agent_id, "owner_message", "data"))
    assert "moved to studio" in str(err.value) and "pegged" not in str(err.value)


def test_a_data_wake_of_an_existing_agent_ignores_a_pegged_machine_but_minting_is_still_refused(env, monkeypatch):
    from src.core.swarm import admission

    monkeypatch.setattr(admission, "measure", lambda: admission.Machine(25.0, 22.0, 10, 60.0))
    calls = []
    _stub_start(monkeypatch, env, calls)
    with closing(connect(db_path_for(env.state_dir), create=False)) as conn:
        agent = store.get_agent(conn, env.agent_id)
        assert "pegged" in body.caps_refusal(conn, agent)
    result = asyncio.run(body.wake(object(), env.agent_id, "crosstalk", "data"))
    assert result.started and calls == ["fresh"]
