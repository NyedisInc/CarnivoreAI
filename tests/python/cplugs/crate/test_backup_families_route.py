
from __future__ import annotations

from pathlib import Path

import pytest

from tests.python.cplugs.crate.api_world import BASE, ApiWorld
from tests.python.cplugs.crate.crate_world import UUID_A

URL = BASE + "/backup-families"
SESSION = {"scope": "session", "target": UUID_A}


def test_needs_the_bearer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with ApiWorld(tmp_path, monkeypatch).client(authed=False) as client:
        assert client.post(URL, json=SESSION).status_code == 401


def test_answers_409_while_the_plugin_is_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with ApiWorld(tmp_path, monkeypatch, on=False).client() as client:
        assert client.post(URL, json=SESSION).status_code == 409


def test_a_session_scope_answers_the_conversations_and_no_folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with ApiWorld(tmp_path, monkeypatch).client() as client:
        resp = client.post(URL, json=SESSION)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["folders"] == []
    assert "available" in body["conversations"]


@pytest.mark.parametrize("body", [{"scope": "session"}, {"target": UUID_A}, {**SESSION, "extra": 1}])
def test_a_malformed_body_is_a_422(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: dict) -> None:
    with ApiWorld(tmp_path, monkeypatch).client() as client:
        assert client.post(URL, json=body).status_code == 422
