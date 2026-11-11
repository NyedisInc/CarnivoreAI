
from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import agent_update_restart_routes as routes_mod
from src.api.auth import require_auth
from src.core.notifications.sources import toast as toast_source


def test_press_restarts_only_the_sessions_the_toast_names(monkeypatch):
    import src.api.session_attach_routes as attach
    from src.core.attention.evidence import STATE_DONE_IDLE

    class Rows:
        async def get_session_info(self, sid):
            return SimpleNamespace(session=SimpleNamespace(id=sid), activity_status="idle", tmux_session="t_" + sid)

    evidence = SimpleNamespace(agent_family=None, registry=SimpleNamespace(known=True, pid=1, version=(2, 1, 1)), background_open=0)
    watcher = SimpleNamespace(observation_for=lambda sid: SimpleNamespace(stale=False, revision=1, evidence=evidence, verdict=SimpleNamespace(state=STATE_DONE_IDLE)))
    monkeypatch.setattr("src.core.notifications.sources.agent_update.agent_update_status", lambda **kw: SimpleNamespace(ready=True, installed="2.1.9"))
    monkeypatch.setattr("src.core.notify_caps.effects.FRESH_WAIT_SECONDS", 0)
    monkeypatch.setattr("src.core.attention.background_claims.standing_background_claims", lambda _e: 0)
    monkeypatch.setattr("src.core.attention.workflow_activity.workflow_active", lambda _e: None)
    monkeypatch.setattr("src.core.attention.fresh_observation.watcher_of", lambda _m: watcher)
    toast = SimpleNamespace(id="toast1", kind="Notification", title="t", body="b", session_id="ses_A", session_label="", version=1,
                            notify_type="agent.update_ready")
    other = SimpleNamespace(id="toast2", kind="Notification", title="t", body="b", session_id="ses_A", session_label="", version=1,
                            notify_type="session.finished")
    monkeypatch.setattr("src.core.toast_history.buckets_from_inbox", lambda _i: {"ses_A": [toast, other]})
    monkeypatch.setattr(toast_source.common, "session_fields", lambda _m, _s: {})
    toast_source.remember_hint("toast1", {"ids": ["ses_A"], "sessions": ["A"], "to": "2.0"})
    calls = []

    async def fake_respawn(manager, name, **kw):
        calls.append((name, kw))
        return {"ok": True}

    monkeypatch.setattr(attach, "respawn_or_http", fake_respawn)
    app = FastAPI()
    app.include_router(routes_mod.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    app.state.session_manager = Rows()
    app.state.session_manager._toast_inbox = object()
    client = TestClient(app)

    answer = client.post("/api/v1/notifications/agent-update/restart", json={"toast_id": "toast1"})
    assert answer.status_code == 200 and answer.json()["restarted"] == 1
    assert [c[0] for c in calls] == ["t_ses_A"]
    assert client.post("/api/v1/notifications/agent-update/restart", json={"toast_id": "nope"}).status_code == 404
    assert client.post("/api/v1/notifications/agent-update/restart", json={"toast_id": "toast2"}).status_code == 422
    assert len(calls) == 1
