
from __future__ import annotations

import asyncio
import os
import tempfile
from types import SimpleNamespace

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ne_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ne_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

import pytest  # noqa: E402

from src.core.crosstalk import bus  # noqa: E402
from src.core.notify_caps import act as act_mod  # noqa: E402
from src.core.notify_caps import effects  # noqa: E402
from src.core.notify_caps import store as store_mod  # noqa: E402
from src.core.notify_media import store as media_mod  # noqa: E402

FP = "b" * 64
REMOTE = "remote:peer-abcd:carnivore_x"


class Manager:
    def __init__(self) -> None:
        self.info = SimpleNamespace(session=SimpleNamespace(id="ses_1"), label="api-docs", tmux_session="carnivore_x")

    async def get_session_info(self, sid):
        return self.info if sid == "ses_1" else None


@pytest.fixture
def rig(monkeypatch, tmp_path):
    monkeypatch.setattr(store_mod, "db_path", lambda: tmp_path / "notify_caps.db")
    monkeypatch.setattr(media_mod, "media_dir", lambda: tmp_path)
    monkeypatch.setattr(act_mod, "watcher_of", lambda _m: None)
    state = SimpleNamespace(session_manager=Manager(), native_device_store=SimpleNamespace(list=lambda: [{"id": "d1"}]))

    def press(target, actions, action, text=None, kind="finished"):
        cap, _ = store_mod.get_store().mint(device_row_id="d1", type_id="t", kind=kind, target=target, actions=actions,
                                            card={"agent": "api-docs"}, ask=False)
        return asyncio.run(act_mod.act(store_mod.get_store(), state, cap, action, text))

    return press


def test_reply_goes_through_the_bus_as_the_owner(rig, monkeypatch):
    calls = []

    async def fake_send(view, caller, **kw):
        calls.append((caller.token_name, kw))
        return {"receipt": "delivered"}

    monkeypatch.setattr(bus, "send", fake_send)
    status, body = rig({"type": "send", "session": "ses_1", "thread": "t-1"}, {"reply": "reply"}, "reply", "ok go")
    assert (status, body["state"], body["agent"]) == (200, "sent", "api-docs")
    assert calls == [("owner", {"to": "ses_1", "text": "ok go", "thread": "t-1", "owner_approved": True})]
    assert rig({"type": "send", "session": "ses_1"}, {"reply": "reply"}, "reply")[0] == 422
    assert rig({"type": "send", "session": "ses_1"}, {"reopen": "reopen"}, "reopen")[0] == 422
    assert len(calls) == 1


def test_reopen_respawns_without_kill(rig, monkeypatch):
    import src.api.session_attach_routes as routes

    calls = []

    async def fake_respawn(manager, name, **kw):
        calls.append((name, kw))
        return {"ok": True}

    monkeypatch.setattr(routes, "respawn_or_http", fake_respawn)
    status, body = rig({"type": "reopen", "session": "ses_1"}, {"reopen": "reopen"}, "reopen", kind="died")
    assert (status, body["state"]) == (200, "sent")
    assert calls == [("carnivore_x", {"live_restart_confirmed": False})]
    async def live(manager, name, **kw):
        return {"ok": False, "kind": "pane_live"}

    monkeypatch.setattr(routes, "respawn_or_http", live)
    assert rig({"type": "reopen", "session": "ses_1"}, {"reopen": "reopen"}, "reopen", kind="died")[0] == 409


def test_app_update_install(rig, monkeypatch):
    import src.api.app_update_routes as routes

    calls = []

    async def fake_install():
        calls.append(1)
        return {}

    monkeypatch.setattr(routes, "install_now", fake_install)
    status, body = rig({"type": "app_update"}, {"install": "install"}, "install", kind="appupdate")
    assert (status, body["state"]) == (200, "sent") and calls == [1]


def test_remote_session_is_forwarded_with_the_stored_choice(rig, monkeypatch):
    forwarded = []
    peer = SimpleNamespace(session=SimpleNamespace(id=REMOTE), label="cv-remote", tmux_session="carnivore_x")

    async def fake_infos(*, force=False):
        return [peer]

    async def fake_forward(info, method, template, body=None):
        forwarded.append((info.session.id, method, template, body))
        return {}

    monkeypatch.setattr(effects.federated, "peer_infos", fake_infos)
    monkeypatch.setattr(effects.federated, "forward", fake_forward)
    status, body = rig({"type": "dialog", "session": REMOTE, "fingerprint": FP}, {"opt.1": "Blue"}, "opt.1", kind="choice")
    assert (status, body) == (200, {"state": "sent", "agent": "cv-remote", "working": False})
    assert forwarded == [(REMOTE, "POST", "/sessions/{session_id}/dialog/answer",
                          {"fingerprint": FP, "choice": {"option": "Blue"}, "source": "owner_phone"})]
    async def refuse(info, method, template, body=None):
        raise effects.ToolError("refused (409): dialog_changed")

    monkeypatch.setattr(effects.federated, "forward", refuse)
    assert rig({"type": "dialog", "session": REMOTE, "fingerprint": FP}, {"yes": "Yes"}, "yes", kind="yesno") == (
        409, {"error": "already_answered", "where": "elsewhere"})


def test_restart_agents_restarts_only_the_idle_live_named_session_with_the_kill_armed(rig, monkeypatch, tmp_path):
    import src.api.session_attach_routes as routes
    from src.core.attention.evidence import STATE_BUSY, STATE_DONE_IDLE

    rows = {"ses_idle": ("idle", STATE_DONE_IDLE), "ses_busy": ("working", STATE_BUSY), "ses_dead": ("dead", STATE_DONE_IDLE),
            "ses_extra": ("idle", STATE_DONE_IDLE),
            "ses_updated": ("idle", STATE_DONE_IDLE), "ses_bg": ("idle", STATE_DONE_IDLE)}

    class Rows:
        async def get_session_info(self, sid):
            row = rows.get(sid)
            return SimpleNamespace(session=SimpleNamespace(id=sid), activity_status=row[0], tmux_session="t_" + sid) if row else None

    def observe(sid):
        if sid not in rows:
            return None
        evidence = SimpleNamespace(agent_family=None, registry=SimpleNamespace(known=True, pid=2 if sid == "ses_updated" else 1, version=(2, 1, 1)),
                                   background_open=1 if sid == "ses_bg" else 0)
        return SimpleNamespace(stale=False, revision=1, evidence=evidence, verdict=SimpleNamespace(state=rows[sid][1]))

    from src.core.notifications.sources import agent_update
    monkeypatch.setattr(agent_update, "agent_update_status", lambda pid, registry_version: SimpleNamespace(ready=pid == 1, installed="2.1.9"))
    monkeypatch.setattr(effects, "FRESH_WAIT_SECONDS", 0)
    monkeypatch.setattr("src.core.attention.background_claims.standing_background_claims", lambda _e: 0)
    monkeypatch.setattr("src.core.attention.workflow_activity.workflow_active", lambda _e: None)
    watcher = SimpleNamespace(observation_for=observe)
    monkeypatch.setattr(act_mod, "watcher_of", lambda _m: watcher)
    monkeypatch.setattr("src.core.attention.fresh_observation.watcher_of", lambda _m: watcher)
    calls = []

    async def fake_respawn(manager, name, **kw):
        calls.append((name, kw))
        return {"ok": True}

    monkeypatch.setattr(routes, "respawn_or_http", fake_respawn)
    state = SimpleNamespace(session_manager=Rows(), native_device_store=SimpleNamespace(list=lambda: [{"id": "d1"}]))

    def press(target, actions, action, text=None):
        cap, _ = store_mod.get_store().mint(device_row_id="d1", type_id="t", kind="update", target=target, actions=actions, card={"agent": "claude"}, ask=False)
        return asyncio.run(act_mod.act(store_mod.get_store(), state, cap, action, text))

    named = {"type": "agent_update", "sessions": ["ses_idle", "ses_busy", "ses_dead", REMOTE, "ses_gone", "ses_updated", "ses_bg"]}
    status, body = press(named, {"restart_agents": "restart them"}, "restart_agents", "ses_extra")
    assert (status, body["restarted"], body["skipped"]) == (200, 1, 6)
    assert calls == [("t_ses_idle", {"live_restart_confirmed": True, "require_agent_resume": True, "live_restart_reason": "agent_update"})]
    calls.clear()
    assert press(named, {"later": "later"}, "restart_agents")[0] == 422
    assert press({"type": "agent_update", "sessions": ["ses_busy", "ses_dead"]}, {"restart_agents": "x"}, "restart_agents")[1]["reason"] == "nothing_restarted"
    assert calls == []
