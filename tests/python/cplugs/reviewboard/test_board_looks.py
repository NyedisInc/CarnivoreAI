
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api import row_looks_routes
from src.core import row_looks
from src.core.browser_pages import open_pages, select
from src.core.row_looks.palette import COLORS, ICONS
from src.cplugs.reviewboard.mcp import TOOLS
from src.models.row_looks import RowLookRequest
from tests.python.cplugs.reviewboard.test_board_page import SLUG, make_board
from tests.python.cplugs.reviewboard.test_publish import HTML, client, create_body, env, item  # noqa: F401
from tests.python.cplugs.reviewboard.harness import BASE


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path: Path):
    topics: list = []
    monkeypatch.setattr(select.resource_push, "notify", lambda topic: None)
    monkeypatch.setattr(open_pages.resource_push, "notify", lambda topic: None)
    monkeypatch.setattr(row_looks.registry.resource_push, "notify", topics.append)
    for reset in (open_pages.reset_for_test, select.reset_for_test, row_looks.reset_for_test):
        reset()
    row_looks.configure(tmp_path / "looks")
    isolated.topics = topics
    yield topics
    for reset in (open_pages.reset_for_test, select.reset_for_test, row_looks.reset_for_test):
        reset()


def _board(env) -> None:
    make_board(env.root)


def test_unset_leaves_the_table_empty_and_the_row_plain(env):
    _board(env)
    ok, out = env.call("task_manager_board_focus", {"board": SLUG})
    assert ok, out
    assert row_looks.listing() == {}


def test_focus_styles_the_row_it_opens_and_the_restyle_tool_finds_it(env):
    _board(env)
    ok, out = env.call("task_manager_board_focus", {"board": SLUG, "color": "cyan", "icon": "docs"})
    assert ok, out
    row = out["page"]["id"]
    assert row_looks.listing() == {row: row_looks.Look("cyan", "docs")}
    assert "row_looks" in isolated.topics
    body = RowLookRequest(color="coral", icon=None)
    answer = asyncio.run(row_looks_routes.set_row_look(row, body, None))
    assert (answer.color, answer.icon) == ("coral", None)
    assert open_pages.close(row) and row_looks.listing() == {}


@pytest.mark.parametrize("args,needle", [({"color": "#ff0000"}, "valid colors"), ({"icon": "nope"}, "valid icons: docs")])
def test_focus_refuses_an_unknown_name_and_opens_nothing(env, args, needle):
    _board(env)
    ok, out = env.call("task_manager_board_focus", {"board": SLUG, **args})
    assert not ok and needle in out
    assert open_pages.listing() == [] and row_looks.listing() == {}


def test_create_gives_the_follow_the_newest_row_its_look_and_a_revision_row_inherits_it(env, item, tmp_path):
    page = tmp_path / "page.html"
    page.write_text(HTML)
    args = {"name": "looks", "title": "looks board", "task": item, "summary": "first", "file_path": str(page), "viewport": 320,
            "color": "violet", "icon": "star"}
    ok, created = env.call("task_manager_board_create", args)
    assert ok, created
    slug = created["slug"]
    ok, out = env.call("task_manager_board_focus", {"board": slug})
    assert ok, out
    assert row_looks.listing()[out["page"]["id"]] == row_looks.Look("violet", "star")
    ok, rev = env.call("task_manager_board_focus", {"board": slug, "revision": "r1"})
    assert ok and rev["page"]["id"] != out["page"]["id"]
    assert row_looks.listing()[rev["page"]["id"]] == row_looks.Look("violet", "star")


def test_create_without_a_look_and_a_bad_look(env, item, tmp_path):
    page = tmp_path / "page.html"
    page.write_text(HTML)
    args = {"name": "plain", "title": "plain board", "task": item, "summary": "first", "file_path": str(page), "viewport": 320}
    ok, created = env.call("task_manager_board_create", args)
    assert ok, created
    assert row_looks.listing() == {}
    ok, text = env.call("task_manager_board_create", {**args, "name": "bad", "color": "magenta"})
    assert not ok and "color" in text


def test_the_route_bodies_take_a_look(env, client: TestClient, item):
    answer = client.post(f"{BASE}/boards", json=create_body(item, color="green", icon="rocket"))
    assert answer.status_code == 200, answer.text
    slug = answer.json()["slug"]
    opened = client.post(f"{BASE}/boards/{slug}/open", json={})
    assert opened.status_code == 200
    assert row_looks.listing()[opened.json()["page"]["id"]] == row_looks.Look("green", "rocket")
    assert client.post(f"{BASE}/boards/{slug}/open", json={"icon": "nope"}).status_code == 422


def test_the_tool_enums_are_the_one_palette():
    for name in ("task_manager_board_create", "task_manager_board_focus"):
        props = TOOLS[name].properties
        assert props["color"]["enum"] == list(COLORS) and props["icon"]["enum"] == list(ICONS)
    assert "color" not in TOOLS["task_manager_board_revision_add"].properties


@pytest.mark.parametrize("model_path", [
    "src.cplugs.reviewboard.requests:CreateBody",
    "src.cplugs.reviewboard.requests:OpenBody",
    "src.cplugs.reviewboard.live_requests:LiveCreateBody",
])
def test_every_body_with_a_look_checks_both_names_through_the_one_mixin(model_path: str) -> None:
    import importlib

    from pydantic import ValidationError

    from src.cplugs.reviewboard.requests import LookChecked

    module, name = model_path.split(":")
    model = getattr(importlib.import_module(module), name)
    assert issubclass(model, LookChecked)
    assert list(model.model_fields)[-2:] == ["color", "icon"]
    for field in ("color", "icon"):
        with pytest.raises(ValidationError) as caught:
            model.model_validate({field: "not-a-listed-name"})
        assert any(err["loc"] == (field,) for err in caught.value.errors())
