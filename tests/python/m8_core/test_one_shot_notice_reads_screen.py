from __future__ import annotations

from src.core.session_status import STATUS_NOTICE
from tests.test_one_shot_route import CREATED_ID, _client, _screen


def test_notice_with_a_dialog_on_screen_refuses(monkeypatch) -> None:
    _screen(monkeypatch, "open")
    client, backend = _client(activity_status=STATUS_NOTICE)
    response = client.post(f"/sessions/{CREATED_ID}/skills/one-shot", json={"text": "answer"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "pane_dialog_open"
    assert backend.pastes == []


def test_notice_with_a_clear_screen_still_pastes(monkeypatch) -> None:
    _screen(monkeypatch, "clear")
    client, backend = _client(activity_status=STATUS_NOTICE)
    assert client.post(f"/sessions/{CREATED_ID}/skills/one-shot", json={"text": "hi"}).status_code == 200
    assert backend.pastes == ["hi"]
