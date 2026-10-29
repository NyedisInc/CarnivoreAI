
from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from typing import List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import browser_open_routes
from src.api.auth import require_auth
from src.core.browser_pages import app_open, open_pages
from src.cplugs.host import page_owner, runtime
from src.cplugs.host import state as owner_state
from src.cplugs.host.runtime import find
from src.cplugs.sdk import manifest as manifest_mod

BOARD = "/static/popout.html?tab=reviewboard&board=demo"
PLAIN = "/static/popout.html?tab=notaplugin&item=3"


@pytest.fixture
def h(tmp_path: Path):
    open_pages.reset_for_test()
    pushed: List[str] = []
    host = runtime.Host(tmp_path, publish=pushed.append)
    app = FastAPI()
    app.state.cplugs_host = host
    app.include_router(browser_open_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    yield type("H", (), {"client": TestClient(app), "host": host, "pushed": pushed, "dir": tmp_path})
    open_pages.reset_for_test()


def _pages(h) -> List[dict]:
    return h.client.get("/api/v1/browsers/pages").json()["pages"]


def _switch(h, enabled: bool) -> None:
    d = find("reviewboard")
    owner_state.update(h.dir, d.manifest, None, lambda st: dataclasses.replace(st, enabled=enabled))
    asyncio.run(h.host.switched("reviewboard", enabled))


def test_a_disabled_plugin_page_is_left_out_and_returns_when_enabled(h):
    app_open.open_app_page(BOARD, "the board")
    app_open.open_app_page(PLAIN, "plain")
    assert not h.host.enabled("reviewboard")
    assert [p["title"] for p in _pages(h)] == ["plain"]
    assert [p.title for p in open_pages.listing()] == ["the board", "plain"]
    _switch(h, True)
    assert [p["title"] for p in _pages(h)] == ["the board", "plain"]
    _switch(h, False)
    assert [p["title"] for p in _pages(h)] == ["plain"]


def test_each_page_carries_its_plugins_section_or_none(h):
    _switch(h, True)
    app_open.open_app_page(BOARD, "the board")
    app_open.open_app_page(PLAIN, "plain")
    open_pages.open_page("huddle_artifact:1:0a1b2c3d", "sandboxed", "art", ref={"item": 1, "artifact": "0a1b2c3d"}, src="/x")
    assert {p["title"]: p["section"] for p in _pages(h)} == {"the board": "review", "plain": None, "art": None}


def test_a_plugin_switch_names_the_pages_topic(h):
    _switch(h, True)
    assert h.pushed == ["browser_pages"]


def test_tab_of_reads_only_app_keys():
    assert page_owner.tab_of("app:/static/popout.html?tab=reviewboard&board=x") == "reviewboard"
    assert page_owner.tab_of("huddle_artifact:1:0a1b2c3d") is None
    assert page_owner.tab_of("app:/static/popout.html") is None


@pytest.mark.parametrize("surfaces", [{"page_section": "Review", "tabs": ["x"]}, {"page_section": "review"}, {"page_section": 3, "tabs": ["x"]}])
def test_a_bad_page_section_is_refused(surfaces):
    with pytest.raises(manifest_mod.ManifestError):
        manifest_mod._surfaces("x", surfaces)


def test_a_page_section_needs_its_label_and_icon_and_the_shipped_one_has_them():
    good = {"tabs": ["x"], "page_section": "review", "page_section_label_key": "cplug.x.section", "page_section_icon": "eye"}
    assert manifest_mod._surfaces("x", good).page_section_icon == "eye"
    for broken in ({**good, "page_section_label_key": "other.section"}, {**good, "page_section_icon": "Eye"},
                   {"tabs": ["x"], "page_section": "review"}, {"tabs": ["x"], "page_section_icon": "eye"}):
        with pytest.raises(manifest_mod.ManifestError):
            manifest_mod._surfaces("x", broken)
    shipped = find("reviewboard").manifest.surfaces
    assert (shipped.page_section, shipped.page_section_label_key, shipped.page_section_icon) == ("review", "cplug.reviewboard.page_section", "eye")


def test_a_flow_page_lists_under_review_while_flow_is_on(h):
    app_open.open_app_page("/static/popout.html?tab=flow&item=395", "flow chart")
    assert _pages(h) == []
    owner_state.update(h.dir, find("flow").manifest, None, lambda st: dataclasses.replace(st, enabled=True))
    assert [(p["title"], p["section"]) for p in _pages(h)] == [("flow chart", "review")]
    assert find("flow").manifest.surfaces.page_section == find("reviewboard").manifest.surfaces.page_section
