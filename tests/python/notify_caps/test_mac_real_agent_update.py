
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import agent_update_restart_routes as routes_mod
from src.api.auth import require_auth
from src.core.notifications import contracts
from src.core.notifications.sources import agent_update, toast as toast_source


def test_real_event_records_a_toast_and_the_press_restarts_its_stored_sessions(monkeypatch, tmp_path):
    import src.api.session_attach_routes as attach
    from src.core.attention.evidence import STATE_DONE_IDLE

    class Rows:
        _toast_inbox = object()
        toasts = []

        async def get_session_info(self, sid):
            return SimpleNamespace(session=SimpleNamespace(id=sid), activity_status="idle", tmux_session="t_" + sid)

        def record_toast(self, session_id, kind, title, body=None, *, notify_type=None):
            toast = SimpleNamespace(id="toast1", kind=kind, title=title, body=body, session_id=session_id, session_label="", version=1, notify_type=notify_type)
            self.toasts.append(toast)
            return toast

    evidence = SimpleNamespace(agent_family=None, registry=SimpleNamespace(known=True, pid=1, version=(2, 1, 1)), background_open=0)
    observed = {"ses_A": SimpleNamespace(stale=False, revision=1, evidence=evidence, verdict=SimpleNamespace(state=STATE_DONE_IDLE))}
    watcher = SimpleNamespace(observed_session_ids=lambda: list(observed), observation_for=lambda sid: observed.get(sid) or observed["ses_A"])
    manager = Rows()
    emitted = []
    monkeypatch.setattr(contracts, "_sink", emitted.append)
    monkeypatch.setattr("src.core.notifications.sources.agent_update.agent_update_status", lambda **kw: SimpleNamespace(ready=True, installed="2.1.9"))
    monkeypatch.setattr("src.core.notifications.agent_message._broadcast", lambda toast: asyncio.sleep(0))
    monkeypatch.setattr("src.core.notify_caps.effects.FRESH_WAIT_SECONDS", 0)
    monkeypatch.setattr("src.core.attention.background_claims.standing_background_claims", lambda _e: 0)
    monkeypatch.setattr("src.core.attention.workflow_activity.workflow_active", lambda _e: None)
    monkeypatch.setattr("src.core.attention.fresh_observation.watcher_of", lambda _m: watcher)
    monkeypatch.setattr("src.core.toast_history.buckets_from_inbox", lambda _i: {"ses_A": manager.toasts})
    monkeypatch.setattr(toast_source.common, "session_fields", lambda _m, _s: {})
    calls = []

    async def fake_respawn(mgr, name, **kw):
        calls.append(name)
        return {"ok": True}

    monkeypatch.setattr(attach, "respawn_or_http", fake_respawn)

    async def fire():
        agent_update.install(lambda: watcher, lambda: manager, asyncio.get_running_loop())
        fired = agent_update.check_once(watcher, state_dir=tmp_path, manager=manager)
        await asyncio.sleep(0.05)
        return fired

    assert asyncio.run(fire()) is True
    assert len(emitted) == 1 and [t.id for t in manager.toasts] == ["toast1"] and manager.toasts[0].notify_type == "agent.update_ready"
    observed["ses_B"] = observed["ses_A"]
    app = FastAPI()
    app.include_router(routes_mod.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    app.state.session_manager = manager
    answer = TestClient(app).post("/api/v1/notifications/agent-update/restart", json={"toast_id": "toast1"})
    assert answer.status_code == 200 and answer.json()["restarted"] == 1
    assert calls == ["t_ses_A"]
