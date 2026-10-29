
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from src.core.browser_pages import resolvers
from src.cplugs import huddle
from src.cplugs.host import runtime
from src.cplugs.huddle import artifact_browser
from tests.python.cplugs.huddle.test_task_manager_artifacts import (  # noqa: F401
    BASE, PAGE, app, client, item, post, signing_secret, upload_caps)


@pytest.fixture
def resolve(app):
    return artifact_browser.resolver(runtime.host_for(app).context("huddle"))


async def _nothing(*_args, **_kwargs):
    return False


def test_the_plugin_registers_the_resolver_and_drops_it_when_it_stops(app, client, monkeypatch):
    resolvers.reset_for_test()
    for name in ("start", "stop"):
        monkeypatch.setattr(huddle.schedule, name, lambda *a, **k: None)
    monkeypatch.setattr(huddle.legacy_approvals, "retire", _nothing)
    monkeypatch.setattr(huddle, "_dealing_step", _nothing)
    ctx = runtime.host_for(app).context("huddle")
    asyncio.run(huddle._start(ctx))
    assert "huddle_artifact" in resolvers._resolvers
    asyncio.run(huddle._stop(ctx))
    assert "huddle_artifact" not in resolvers._resolvers


def test_an_artifact_resolves_to_the_dialogs_ticketed_viewer_path(client, item, resolve):
    artifact = post(client, item).json()["message"]["artifact"]
    page = asyncio.run(resolve({"item": item, "artifact": artifact["id"]}))
    assert page.path.startswith(f"{BASE}/artifact-view/") and "?" not in page.path and page.title == "Layout A"
    assert page.path.startswith(resolvers.PATH_PREFIX)
    minted = client.post(f"{BASE}/items/{item}/artifacts/{artifact['id']}/ticket").json()["url"]
    assert minted.rsplit("/", 1)[0] == page.path.rsplit("/", 1)[0]


def test_a_page_that_is_not_an_artifact_of_that_item_is_not_found(client, item, resolve):
    artifact = post(client, item).json()["message"]["artifact"]
    with pytest.raises(resolvers.PageNotFound):
        asyncio.run(resolve({"item": item + 1, "artifact": artifact["id"]}))
    with pytest.raises(resolvers.PageNotFound):
        asyncio.run(resolve({"item": item, "artifact": "ffffffff"}))


def test_the_viewer_is_the_same_locked_down_page_and_needs_its_ticket(app, client, item, resolve):
    artifact = post(client, item).json()["message"]["artifact"]
    page = asyncio.run(resolve({"item": item, "artifact": artifact["id"]}))
    ticket = page.path.rsplit("/", 1)[1]
    app.dependency_overrides.clear()
    with TestClient(app) as anonymous:
        r = anonymous.get(page.path)
        assert r.status_code == 200 and r.text == PAGE
        csp = r.headers["content-security-policy"]
        assert "sandbox allow-scripts" in csp and "connect-src 'none'" in csp and "allow-same-origin" not in csp
        assert "frame-ancestors 'self'" in csp
        assert anonymous.get(f"{BASE}/artifact-view/garbage").status_code == 404
        assert anonymous.get(f"{BASE}/artifact-view?ticket={ticket}").status_code == 404
