
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import codex_helpers_routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.api.timeline import routes as timeline_routes  # noqa: E402
from src.core.codex_helpers import runtime  # noqa: E402
from src.core.timeline import gate  # noqa: E402
from tests.python.notifications.test_styles_routes import BASE, client  # noqa: E402,F401


def test_session_sounds_lists_every_offered_type_and_refuses_a_bad_name(client) -> None:
    body = client.get(f"{BASE}/session-sounds", params={"name": "cloude_a"}).json()
    assert set(body["types"]) == {"session.question", "session.permission", "session.plan_approval", "session.finished", "session.died"}
    assert body["types"]["session.died"]["override"] is None and body["types"]["session.died"]["global"]
    assert client.get(f"{BASE}/session-sounds", params={"name": "bad name!"}).status_code == 422


def test_play_answers_the_sound_for_a_type_and_refuses_an_unknown_type(client) -> None:
    ok = client.get(f"{BASE}/play", params={"type_id": "session.died"})
    assert ok.status_code == 200 and isinstance(ok.json()["sound"], str)
    assert client.get(f"{BASE}/play", params={"type_id": "no.such.type"}).status_code == 422


def test_codex_helpers_check_measures_now_and_answers_the_status(monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(runtime, "check_now", lambda **kw: calls.append(kw))
    monkeypatch.setattr(runtime, "status", lambda: {"armed": True, "check": None})
    app = FastAPI()
    app.include_router(codex_helpers_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    r = TestClient(app).post("/api/v1/agents/codex/helpers/check")
    assert r.status_code == 200 and r.json() == {"armed": True, "check": None}
    assert calls == [{"force": True}]


def test_timeline_threads_is_refused_while_the_switch_is_off(monkeypatch) -> None:
    def off() -> None:
        raise gate.TimelineOff("off")

    monkeypatch.setattr(gate, "require_on", off)
    app = FastAPI()
    app.include_router(timeline_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    r = TestClient(app).get("/api/v1/sessions/ses_1/timeline/threads")
    assert r.status_code == 409 and "timeline_off" in r.text
