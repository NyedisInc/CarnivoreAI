
from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import browser_open_routes, browser_routes
from src.api.auth import require_auth
from src.config.browser import BrowserConfig
from src.core.browser_pages import open_pages, pool, resolvers, select
from src.core.browsers.manager import BrowserManager, CapReached
from src.core.db_migration import ensure_db_migrated
from src.core.mcp import tools
from src.cplugs.host import state as owner_state
from src.cplugs.host.runtime import Host, find
from src.core.resource_push.topics import BROWSER_PAGES, BROWSER_SELECT, RESOURCE_TOPICS

API = "/api/v1"
TICKETED = "/api/v1/cplugs/huddle/artifact-view/1.0a1b2c3d.9999999999.sig"


class FakeLive:

    def __init__(self, browser_id: str, url: str) -> None:
        self.id = browser_id
        self.viewers: set = set()
        self.idle_task = None
        self.stopping = False
        self.urls = [url]

    async def navigate(self, url: str) -> None:
        self.urls.append(url)

    async def close(self) -> None:
        return None


class FakeManager(BrowserManager):

    def __init__(self, state_dir: Path, max_live: int) -> None:
        super().__init__(state_dir, lambda: BrowserConfig(max_live=max_live, idle_stop_minutes=5))
        self.launched: List[tuple] = []

    async def _launch(self, browser_id, url):
        if len(self.live) >= self._config().max_live:
            raise CapReached(f"cap is {self._config().max_live}")
        self.launched.append((browser_id, url))
        live = FakeLive(browser_id, url)
        self.live[browser_id] = live
        return live

    async def _open_url(self, live, url) -> None:
        pass


def _harness(tmp_path: Path, monkeypatch, max_live: int = 4) -> SimpleNamespace:
    assert ensure_db_migrated(tmp_path).status == "ok"
    pool.reset_for_test()
    select.reset_for_test()
    resolvers.reset_for_test()
    open_pages.reset_for_test()
    pushed: List[str] = []
    pages_pushed: List[str] = []
    monkeypatch.setattr(select.resource_push, "notify", lambda topic: (pushed if topic == BROWSER_SELECT else pages_pushed).append(topic) if topic in (BROWSER_SELECT, BROWSER_PAGES) else None)
    manager = FakeManager(tmp_path, max_live)
    app = FastAPI()
    app.state.browser_manager = manager
    app.state.cplugs_host = Host(tmp_path)
    flow = find("flow")
    owner_state.update(tmp_path, flow.manifest, None, lambda st: dataclasses.replace(st, enabled=True))
    app.include_router(browser_routes.router, prefix=API)
    app.include_router(browser_open_routes.router, prefix=API)
    app.dependency_overrides[require_auth] = lambda: True
    return SimpleNamespace(client=TestClient(app), app=app, manager=manager, pushed=pushed, pages_pushed=pages_pushed, state_dir=tmp_path)


@pytest.fixture
def h(tmp_path, monkeypatch):
    yield _harness(tmp_path, monkeypatch)
    pool.reset_for_test()
    select.reset_for_test()
    resolvers.reset_for_test()
    open_pages.reset_for_test()


def _open(h, **body):
    return h.client.post(f"{API}/browsers/open", json=body)


def _rows(h) -> List[dict]:
    return h.client.get(f"{API}/browsers").json()["browsers"]


def test_the_topics_are_advertised():
    assert BROWSER_SELECT in RESOURCE_TOPICS and BROWSER_PAGES in RESOURCE_TOPICS


def test_a_url_opens_a_labeled_session_and_pushes_the_select(h):
    assert h.client.get(f"{API}/browsers/selected").json() == {"select": None}
    r = _open(h, url="https://example.com/docs?x=1", title="the docs")
    assert r.status_code == 200, r.text
    body = r.json()
    browser, chosen = body["browser"], body["select"]
    assert browser["label"] == "the docs" and browser["url"] == "https://example.com/docs"
    assert chosen["browser_id"] == browser["id"] and chosen["title"] == "the docs"
    assert h.pushed == [BROWSER_SELECT]
    got = h.client.get(f"{API}/browsers/selected").json()["select"]
    assert got["seq"] == chosen["seq"] and 0 <= got["age_s"] <= select.FRESH_S
    assert [row["id"] for row in _rows(h)] == [browser["id"]]


def test_the_same_page_reuses_its_session_and_a_new_seq_selects_it_again(h):
    first = _open(h, url="https://example.com/a").json()
    again = _open(h, url="https://example.com/a").json()
    assert again["browser"]["id"] == first["browser"]["id"]
    assert again["select"]["seq"] > first["select"]["seq"]
    assert len(h.manager.launched) == 1
    assert h.manager.live[first["browser"]["id"]].urls[-1] == "https://example.com/a"
    assert first["browser"]["label"] == "example.com"


def test_the_pool_holds_two_pages_then_replaces_the_oldest(h):
    a = _open(h, url="https://a.example/").json()["browser"]["id"]
    b = _open(h, url="https://b.example/").json()["browser"]["id"]
    assert a != b and len(_rows(h)) == pool.POOL_SIZE == 2
    c = _open(h, url="https://c.example/", title="c").json()["browser"]
    assert c["id"] == a and c["label"] == "c"
    assert len(_rows(h)) == 2 and h.manager.live[a].urls[-1] == "https://c.example/"
    assert _open(h, url="https://b.example/").json()["browser"]["id"] == b


def test_a_full_live_cap_reuses_a_pool_session_instead_of_refusing(tmp_path, monkeypatch):
    h = _harness(tmp_path, monkeypatch, max_live=1)
    a = _open(h, url="https://a.example/").json()["browser"]["id"]
    r = _open(h, url="https://b.example/")
    assert r.status_code == 200, r.text
    assert r.json()["browser"]["id"] == a and len(_rows(h)) == 1


def test_a_full_cap_with_no_pool_session_is_409(tmp_path, monkeypatch):
    h = _harness(tmp_path, monkeypatch, max_live=1)
    h.manager.live["aaaaaaaaaaaaaaaa"] = FakeLive("aaaaaaaaaaaaaaaa", "about:blank")
    assert _open(h, url="https://a.example/").status_code == 409
    assert h.pushed == []


def test_a_closed_pool_row_is_replaced(h):
    a = _open(h, url="https://a.example/").json()["browser"]["id"]
    assert h.client.delete(f"{API}/browsers/{a}").status_code == 204
    again = _open(h, url="https://a.example/").json()["browser"]["id"]
    assert again != a and [row["id"] for row in _rows(h)] == [again]


def _artifact_resolver(title="Layout A"):
    async def resolve(ref):
        assert ref == {"item": 1, "artifact": "0a1b2c3d"}
        return resolvers.ResolvedPage(path=TICKETED, title=title)

    resolvers.register("huddle_artifact", resolve)


def _pages(h) -> List[dict]:
    return h.client.get(f"{API}/browsers/pages").json()["pages"]


def test_an_artifact_opens_as_a_sandboxed_page_row_and_launches_no_browser(h):
    _artifact_resolver()
    r = _open(h, huddle_artifact={"item": 1, "artifact": "0a1b2c3d"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "browser" not in body
    page = body["page"]
    assert page["key"] == "huddle_artifact:1:0a1b2c3d" and page["src"] == TICKETED and page["frame"] == "sandboxed"
    assert page["title"] == "Layout A" and len(page["id"]) == 16
    assert body["select"]["kind"] == "page" and body["select"]["page_id"] == page["id"] and "page" not in body["select"]
    assert h.pushed == [BROWSER_SELECT] and h.pages_pushed == [BROWSER_PAGES] and h.manager.launched == [] and _rows(h) == []
    got = h.client.get(f"{API}/browsers/selected").json()["select"]
    assert got["seq"] == body["select"]["seq"] and got["page_id"] == page["id"]


@pytest.mark.parametrize("path,title", [
    ("/static/popout.html?tab=flow&item=395", "flow"),
    ("  /static/popout.html?tab=huddle  ", "huddle"),
    ("/static/popout.html", "carnivore"),
])
def test_the_popout_path_opens_as_a_same_origin_page_row(h, path, title):
    r = _open(h, url=path)
    assert r.status_code == 200, r.text
    page = r.json()["page"]
    assert page["frame"] == "app" and page["src"] == path.strip() and page["key"] == f"app:{path.strip()}"
    assert page["title"] == title and r.json()["select"]["title"] == title
    assert h.pushed == [BROWSER_SELECT] and h.pages_pushed == [BROWSER_PAGES] and h.manager.launched == [] and _rows(h) == []


def test_the_same_page_again_reuses_its_row(h):
    first = _open(h, url="/static/popout.html?tab=flow").json()
    again = _open(h, url="/static/popout.html?tab=flow", title="flow two").json()
    assert again["page"]["id"] == first["page"]["id"] and again["select"]["seq"] > first["select"]["seq"]
    assert [p["title"] for p in _pages(h)] == ["flow two"]


def test_the_list_survives_a_reload_and_mints_a_fresh_ticket_each_read(h):
    counter = iter(range(100))

    async def resolve(ref):
        return resolvers.ResolvedPage(path=f"/api/v1/cplugs/huddle/artifact-view/t{next(counter)}", title="A")

    resolvers.register("huddle_artifact", resolve)
    opened = _open(h, huddle_artifact={"item": 1, "artifact": "0a1b2c3d"}).json()["page"]
    _open(h, url="/static/popout.html?tab=flow")
    first, second = _pages(h), _pages(h)
    assert [p["frame"] for p in first] == ["sandboxed", "app"]
    assert first[0]["id"] == opened["id"] and first[0]["src"] != second[0]["src"]
    assert first[1]["src"] == "/static/popout.html?tab=flow" == second[1]["src"]


def test_a_page_whose_artifact_is_gone_stays_a_row_with_no_src(h):
    _artifact_resolver()
    _open(h, huddle_artifact={"item": 1, "artifact": "0a1b2c3d"})
    resolvers.reset_for_test()
    listed = _pages(h)
    assert len(listed) == 1 and listed[0]["src"] is None


def test_closing_a_page_removes_the_row_and_pushes(h):
    _open(h, url="/static/popout.html?tab=flow")
    page = _pages(h)[0]
    h.pages_pushed.clear()
    assert h.client.delete(f"{API}/browsers/pages/{page['id']}").status_code == 204
    assert _pages(h) == [] and h.pages_pushed == [BROWSER_PAGES]
    missing = h.client.delete(f"{API}/browsers/pages/{page['id']}")
    assert missing.status_code == 404 and h.pages_pushed == [BROWSER_PAGES]


def test_the_list_holds_a_bounded_number_of_pages(h):
    for n in range(open_pages.MAX_PAGES + 3):
        assert _open(h, url=f"/static/popout.html?tab=t{n}").status_code == 200
    listed = _pages(h)
    assert len(listed) == open_pages.MAX_PAGES and listed[-1]["title"] == f"t{open_pages.MAX_PAGES + 2}"
    assert "t0" not in [p["title"] for p in listed]


def test_routing_by_target(h):
    _artifact_resolver("A")
    assert set(_open(h, huddle_artifact={"item": 1, "artifact": "0a1b2c3d"}).json()) == {"page", "select"}
    assert set(_open(h, url="/static/popout.html?tab=flow&item=1").json()) == {"page", "select"}
    web = _open(h, url="https://example.com/").json()
    assert set(web) == {"browser", "select"} and web["select"]["kind"] == "browser"
    assert len(h.manager.launched) == 1 and len(_rows(h)) == 1 and len(_pages(h)) == 2


def test_an_artifact_needs_its_plugin_and_an_existing_page(h):
    assert _open(h, huddle_artifact={"item": 1, "artifact": "0a1b2c3d"}).status_code == 409

    async def missing(ref):
        raise resolvers.PageNotFound("gone")

    resolvers.register("huddle_artifact", missing)
    assert _open(h, huddle_artifact={"item": 1, "artifact": "0a1b2c3d"}).status_code == 404
    assert h.pushed == [] and h.pages_pushed == [] and _rows(h) == [] and _pages(h) == []


@pytest.mark.parametrize("body", [
    {"url": "/static/index.html"},
    {"url": "/api/v1/cplugs/flow/run?seed=huddle_item&id=395&html=true"},
    {"url": "/static//popout.html"},
    {"url": "/static/popout.html/"},
    {"url": "/static/popout.html\\..\\index.html"},
    {"url": "//evil.example/static/popout.html"},
    {"url": "file:///etc/passwd"},
    {"url": "https://a.example/", "huddle_artifact": {"item": 1, "artifact": "0a1b2c3d"}},
    {},
    {"huddle_artifact": {"item": 1, "artifact": "../../x"}},
])
def test_refusals(h, body):
    r = _open(h, **body)
    assert r.status_code in (400, 422), r.text
    assert h.pushed == [] and h.pages_pushed == [] and _rows(h) == [] and _pages(h) == []


def test_the_app_path_refusal_names_its_code_and_the_artifact_way(h):
    detail = _open(h, url="/api/v1/cplugs/flow/run?seed=huddle_item&id=395&html=true").json()["detail"]
    assert detail["code"] == "browser_open_app_page" and "huddle_artifact" in detail["detail"]


def test_the_mcp_tool_reaches_the_same_route(h):
    assert "browser_open" in tools._TOOLS and "side_view_open" not in tools._TOOLS
    handler = tools._TOOLS["browser_open"][3]
    result = asyncio.run(handler(SimpleNamespace(app=h.app), None, {"url": "https://example.com/", "title": "x"}))
    text = result["content"][0]["text"] if isinstance(result, dict) and "content" in result else str(result)
    assert "example.com" in text and h.pushed == [BROWSER_SELECT]
