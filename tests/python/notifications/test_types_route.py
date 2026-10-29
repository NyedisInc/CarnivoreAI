
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import notification_types_routes as routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402

URL = "/api/v1/notifications/types"


def _app(authed: bool) -> TestClient:
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    if authed:
        app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app)


def test_authenticated_get_returns_39_types_and_13_kinds() -> None:
    body = _app(True).get(URL).json()
    assert len(body["types"]) == 39 and len(body["kinds"]) == 13
    assert [f["id"] for f in body["families"]] == ["needs_you", "sessions", "accounts", "health", "app", "in_app"]
    first = body["types"][0]
    assert first["id"] == "session.permission" and "screen_locked" not in first["defaults"]
    assert first["label_key"] == "notify.type.session.permission.label"
    by_id = {t["id"]: t for t in body["types"]}
    assert by_id["alert.notifications"]["defaults"]["outside_locked_off"] is True
    assert by_id["session.finished"]["seed_excluded_kinds"] == ["sns", "twilio", "pagerduty"]
    telegram = next(k for k in body["kinds"] if k["id"] == "telegram")
    assert [f["name"] for f in telegram["secret_fields"]] == ["token", "chat_ids"]


def test_response_carries_no_values() -> None:
    text = json.dumps(_app(True).get(URL).json())
    for needle in ("https://", "ntfy.sh", "hooks.slack.com", "\"default\""):
        assert needle not in text, needle


def test_unauthenticated_get_is_refused() -> None:
    assert _app(False).get(URL).status_code in (401, 403)


def test_route_is_included_in_the_aggregator() -> None:
    from src.api.routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    response = TestClient(app).get(URL)
    assert response.status_code == 200 and len(response.json()["types"]) == 39
