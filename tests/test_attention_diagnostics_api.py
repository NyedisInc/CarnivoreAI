
from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.attention_routes import router
from src.api.auth import require_auth
from tests.test_attention_observation_store import START, evidence, watcher
from src.core.attention.watcher import STALL_BACKSTOP_SECONDS, WatchTarget


def test_diagnostic_auth_and_safe_fields() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    clock = [START]
    target = WatchTarget("session", "pane@1")
    observed = watcher(lambda *_: None, [target], clock)
    observed._apply(target, evidence(START))
    app.state.attention_watcher = observed
    client = TestClient(app)
    assert client.get("/api/v1/sessions/attention").status_code == 401
    app.dependency_overrides[require_auth] = lambda: {}
    clock[0] += timedelta(seconds=STALL_BACKSTOP_SECONDS)
    response = client.get("/api/v1/sessions/attention")
    assert response.status_code == 200
    record = response.json()["observations"][0]
    assert record["state"] == "unknown" and record["stale"]
    assert record["age_seconds"] == STALL_BACKSTOP_SECONDS
    assert set(record) == {
        "session_id", "age_seconds", "state", "source", "matched_rule",
        "disagreement_reason", "stale", "revision",
    }


def test_diagnostic_before_watcher_start() -> None:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_auth] = lambda: {}
    assert TestClient(app).get("/sessions/attention").json() == {
        "available": False, "observations": [],
    }
