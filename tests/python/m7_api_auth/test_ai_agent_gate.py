
from __future__ import annotations

from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import ai_invoke_routes
from src.api.auth import require_auth
from src.models.automations import UNATTENDED_PHRASE


class RecordingGateway:

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def target(self, connection: str, model: Any, voice: Any) -> str:
        return connection

    async def agent(self, ref: str, prompt: str, **options: Any) -> Dict[str, Any]:
        self.calls.append({"prompt": prompt, **options})
        return {"text": "ok"}


@pytest.fixture()
def harness(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, RecordingGateway]:
    gateway = RecordingGateway()
    monkeypatch.setattr(ai_invoke_routes.gateway_module, "get_gateway", lambda: gateway)
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: True
    app.include_router(ai_invoke_routes.router, prefix="/api/v1")
    return TestClient(app), gateway


def _post(client: TestClient, **extra: Any):
    return client.post("/api/v1/ai/agent", json={"connection": "c", "prompt": "go", **extra})


@pytest.mark.parametrize("mode", ["bypassPermissions", "dontAsk", "danger-full-access"])
def test_an_unattended_mode_without_the_phrase_is_refused(harness, mode: str) -> None:
    client, gateway = harness
    response = _post(client, permission_mode=mode)
    assert response.status_code == 422
    assert gateway.calls == []


@pytest.mark.parametrize("mode", ["bypassPermissions", "dontAsk"])
def test_the_exact_phrase_lets_it_through(harness, mode: str) -> None:
    client, gateway = harness
    assert _post(client, permission_mode=mode, acknowledge_unattended=UNATTENDED_PHRASE).status_code == 200
    assert gateway.calls and gateway.calls[0]["permission_mode"] == mode
    assert "acknowledge_unattended" not in gateway.calls[0]


def test_a_wrong_phrase_is_refused(harness) -> None:
    client, gateway = harness
    assert _post(client, permission_mode="bypassPermissions", acknowledge_unattended="yes").status_code == 422
    assert gateway.calls == []


@pytest.mark.parametrize("mode", [None, "plan", "acceptEdits", "read-only"])
def test_a_prompted_mode_needs_no_phrase(harness, mode: Any) -> None:
    client, gateway = harness
    assert _post(client, **({"permission_mode": mode} if mode else {})).status_code == 200
    assert len(gateway.calls) == 1
