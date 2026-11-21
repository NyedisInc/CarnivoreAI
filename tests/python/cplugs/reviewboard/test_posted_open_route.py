
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.core.browser_pages import open_pages, select
from tests.python.cplugs.reviewboard.boards import SIDECAR, make_board
from tests.python.cplugs.reviewboard.harness import BASE, Env, make_env

SLUG = SIDECAR["board"]["slug"]
TITLE = SIDECAR["board"]["title"]
ITEM = SIDECAR["task"]["item_id"]
URL = f"{BASE}/posted/open"


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(select.resource_push, "notify", lambda topic: None)
    monkeypatch.setattr(open_pages.resource_push, "notify", lambda topic: None)
    open_pages.reset_for_test()
    select.reset_for_test()
    yield
    open_pages.reset_for_test()
    select.reset_for_test()


@pytest.fixture
def env(tmp_path: Path) -> Env:
    made = make_env(tmp_path)
    make_board(made.root)
    return made


@pytest.fixture
def client(env: Env):
    env.app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(env.app) as test_client:
        yield test_client


def test_posted_open_opens_the_board_held_under_that_task_and_title(client: TestClient) -> None:
    resp = client.post(URL, json={"item": ITEM, "title": TITLE})
    assert resp.status_code == 200, resp.text
    page = resp.json()["page"]
    assert parse_qs(urlsplit(page["src"]).query)["board"] == [SLUG]
    assert [p.id for p in open_pages.listing()] == [page["id"]]


def test_posted_open_answers_404_when_the_task_has_no_such_board(client: TestClient) -> None:
    assert client.post(URL, json={"item": ITEM, "title": "never posted"}).status_code == 404
    assert client.post(URL, json={"item": ITEM + 1000, "title": TITLE}).status_code == 404
    assert open_pages.listing() == []


@pytest.mark.parametrize("body", [{"item": 0, "title": "x"}, {"item": 1, "title": ""}, {"item": 1, "title": "x", "extra": 1}])
def test_posted_open_rejects_a_malformed_body(client: TestClient, body: dict) -> None:
    assert client.post(URL, json=body).status_code == 422


def test_posted_open_needs_the_bearer(env: Env) -> None:
    with TestClient(env.app) as anonymous:
        assert anonymous.post(URL, json={"item": ITEM, "title": TITLE}).status_code in (401, 403)
    assert open_pages.listing() == []
