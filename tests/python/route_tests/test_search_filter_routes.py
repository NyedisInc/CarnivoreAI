
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api import search_index_routes
from tests.python.route_tests.harness import client_for

URL = "/pipeline/search-filter"


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from src.config import settings

    path = tmp_path / "config.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(settings, "auth_config_file", str(path), raising=False)
    return path


def test_get_answers_defaults_overrides_effective_and_versions(config_file: Path) -> None:
    body = client_for(search_index_routes.router).get(URL).json()
    assert set(body) == {"defaults", "overrides", "effective", "versions"}
    assert body["overrides"] == {}
    assert body["effective"]["claude"]["blocks"] == body["defaults"]["blocks"]


def test_put_stores_the_override_and_it_changes_the_effective_rules(config_file: Path) -> None:
    client = client_for(search_index_routes.router)
    put = client.put(URL, json={"overrides": {"blocks": {"thinking": "keep"}}})
    assert put.status_code == 200, put.text
    assert "thinking" in json.dumps(json.loads(config_file.read_text()))
    again = client.get(URL).json()
    assert again["effective"]["claude"]["blocks"]["thinking"] == "keep"
    assert again["versions"]["claude"] != client.put(URL, json={"overrides": {}}).json()["versions"]["claude"]


def test_put_an_empty_override_restores_the_defaults(config_file: Path) -> None:
    client = client_for(search_index_routes.router)
    client.put(URL, json={"overrides": {"blocks": {"thinking": "keep"}}})
    assert client.put(URL, json={"overrides": {}}).json()["overrides"] == {}
    assert client.get(URL).json()["effective"]["claude"]["blocks"]["thinking"] == "drop"


@pytest.mark.parametrize(
    "overrides",
    [{"no_such_rule": 1}, {"blocks": {"thinking": "maybe"}}, {"max_message_chars": 0}, {"blocks": "text"}],
)
def test_put_refuses_invalid_rules_and_leaves_config_alone(config_file: Path, overrides: dict) -> None:
    resp = client_for(search_index_routes.router).put(URL, json={"overrides": overrides})
    assert resp.status_code == 422
    assert config_file.read_text() == "{}"


def test_put_is_a_500_when_config_json_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.config import settings

    missing = tmp_path / "absent.json"
    monkeypatch.setattr(settings, "auth_config_file", str(missing), raising=False)
    resp = client_for(search_index_routes.router).put(URL, json={"overrides": {}})
    assert resp.status_code == 500
    assert not missing.exists()


def test_both_verbs_need_auth(config_file: Path) -> None:
    client = client_for(search_index_routes.router, signed_in=False)
    assert client.get(URL).status_code in (401, 403)
    assert client.put(URL, json={"overrides": {"blocks": {"thinking": "keep"}}}).status_code in (401, 403)
    assert config_file.read_text() == "{}"
