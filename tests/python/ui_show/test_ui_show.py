
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import size_master, ui_show_resolve, ui_show_routes
from src.api.auth import require_auth
from src.core.layouts import store as layouts_store
from src.core.browser_pages import open_pages
from src.core.db import db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError
from src.core.open_files import open_list
from src.core.resource_push.topics import RESOURCE_TOPICS, UI_SHOW
from src.core.ui_show import KINDS, last_window, pointer
from tests.python.browser_pages.test_browser_open import h as browser_h  # noqa: F401
from tests.python.open_files.test_files_open_tool import PANE, _call, h as files_h  # noqa: F401

API = "/api/v1"
ME = "tab-aaaaaaaa-1"
OTHER = "tab-bbbbbbbb-2"


class FakeSessions:

    async def get_session_info(self, session_id):
        if session_id != "ses_live":
            return None
        return SimpleNamespace(tmux_session="carnivore_live", label="live one", session=SimpleNamespace(id="ses_live"))


@pytest.fixture
def ui(tmp_path: Path, monkeypatch):
    assert ensure_db_migrated(tmp_path).status == "ok"
    monkeypatch.setattr(ui_show_resolve, "_db_path", lambda: db_path_for(tmp_path))
    pushed: list = []
    monkeypatch.setattr(pointer.resource_push, "notify", lambda topic: pushed.append(topic))
    last_window.reset_for_test()
    pointer.reset_for_test()
    open_list.reset_for_test()
    open_pages.reset_for_test()
    app = FastAPI()
    app.state.session_manager = FakeSessions()
    app.include_router(ui_show_routes.router, prefix=API)
    app.dependency_overrides[require_auth] = lambda: True
    yield SimpleNamespace(client=TestClient(app), app=app, pushed=pushed)
    last_window.reset_for_test()
    pointer.reset_for_test()
    open_list.reset_for_test()
    open_pages.reset_for_test()


def _ui_pushes(ui) -> list:
    return [topic for topic in ui.pushed if topic == UI_SHOW]


def _active(ui, client_id: str = ME) -> None:
    assert ui.client.post(f"{API}/ui/activity", json={"client_id": client_id}).status_code == 204


def _show(ui, **body):
    return ui.client.post(f"{API}/ui/show", json=body)


def _file_row(tmp_path_name: str = "plan.md") -> str:
    return open_list.open_file("file", "workdir", tmp_path_name, "uuid-1")[0].id


def test_the_topic_is_advertised_and_the_id_pattern_matches_the_size_master():
    assert UI_SHOW in RESOURCE_TOPICS
    assert last_window.CLIENT_ID_PATTERN.pattern == size_master.CLIENT_ID_PATTERN.pattern


@pytest.mark.parametrize("client_id", ["short", "has space in it", "x" * 65, "../../etc/pass", ""])
def test_a_malformed_client_id_is_refused_and_remembered_by_nobody(ui, client_id):
    assert ui.client.post(f"{API}/ui/activity", json={"client_id": client_id}).status_code == 422
    assert last_window.current() is None


def test_no_window_used_answers_409_and_pushes_nothing(ui):
    row = _file_row()
    res = _show(ui, kind="file", id=row)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "ui_show_no_window"
    assert _ui_pushes(ui) == [] and ui.client.get(f"{API}/ui/show").json() == {"show": None}


def test_a_show_is_addressed_to_the_window_used_last_and_pushed_once(ui):
    row = _file_row()
    _active(ui, OTHER)
    _active(ui, ME)
    res = _show(ui, kind="file", id=row)
    assert res.status_code == 200 and res.json()["id"] == row and res.json()["title"] == "plan.md"
    assert _ui_pushes(ui) == [UI_SHOW]
    shown = ui.client.get(f"{API}/ui/show").json()["show"]
    assert shown["target_client_id"] == ME and shown["kind"] == "file" and shown["id"] == row and shown["seq"] == res.json()["seq"]
    assert "target_client_id" not in res.json()
    _active(ui, OTHER)
    _show(ui, kind="file", id=row)
    assert ui.client.get(f"{API}/ui/show").json()["show"]["target_client_id"] == OTHER


def test_a_session_carries_its_tmux_name(ui):
    _active(ui)
    assert _show(ui, kind="session", id="ses_live").status_code == 200
    shown = ui.client.get(f"{API}/ui/show").json()["show"]
    assert shown["id"] == "ses_live" and shown["tmux_session"] == "carnivore_live" and shown["title"] == "live one"


def test_the_task_manager_needs_no_id_and_refuses_one(ui):
    _active(ui)
    assert _show(ui, kind="task_manager").status_code == 200
    assert _show(ui, kind="task_manager", id="12").status_code == 404


def test_a_page_row_shows_as_a_browser_item(ui):
    _active(ui)
    page = open_pages.open_page("k", "app", "flow board", src="/static/popout.html?tab=flow")
    assert _show(ui, kind="browser", id=page.id).json()["title"] == "flow board"


def test_a_layout_is_found_by_uuid(ui, monkeypatch):
    _active(ui)
    assert _show(ui, kind="layout", id="5f0c0000-0000-0000-0000-000000000000").status_code == 404
    monkeypatch.setattr(layouts_store, "get_layout", lambda conn, uuid: SimpleNamespace(layout_uuid=uuid, name="api work"))
    res = _show(ui, kind="layout", id="5f0c0000-0000-0000-0000-000000000000")
    assert res.status_code == 200 and res.json()["title"] == "api work"


@pytest.mark.parametrize("body", [
    {"kind": "session", "id": "ses_gone"}, {"kind": "file", "id": "0123456789abcdef"}, {"kind": "browser", "id": "0123456789abcdef"},
    {"kind": "board", "id": "no-such-board"}, {"kind": "layout", "id": "nope"}, {"kind": "file"}, {"kind": "session"},
])
def test_an_item_that_does_not_exist_is_404_and_pushes_nothing(ui, body):
    _active(ui)
    res = _show(ui, **body)
    assert res.status_code == 404 and res.json()["detail"]["code"] == "ui_show_not_found"
    assert _ui_pushes(ui) == [] and pointer.current() is None


def test_a_malformed_body_is_422(ui):
    _active(ui)
    assert _show(ui, kind="dashboard", id="x").status_code == 422
    assert _show(ui, kind="file", id="x", extra=1).status_code == 422


def test_every_kind_has_a_resolver():
    assert set(KINDS) == set(ui_show_resolve.RESOLVERS)



def test_files_open_front_shows_the_row_in_the_window_used_last(files_h, monkeypatch):
    monkeypatch.setattr(pointer.resource_push, "notify", lambda topic: None)
    last_window.reset_for_test()
    pointer.reset_for_test()
    last_window.touch(ME)
    result = _call(files_h, {"target": "ses_cloude_a", "path": "docs/plan.md", "front": True})
    assert result["front"]["shown"] is True
    shown = pointer.current()
    assert shown["kind"] == "file" and shown["id"] == result["file"]["id"] and shown["target_client_id"] == ME
    last_window.reset_for_test()
    pointer.reset_for_test()


def test_files_open_front_is_off_by_default_and_a_missing_window_never_fails_the_open(files_h, monkeypatch):
    monkeypatch.setattr(pointer.resource_push, "notify", lambda topic: None)
    last_window.reset_for_test()
    pointer.reset_for_test()
    plain = _call(files_h, {"target": "ses_cloude_a", "path": "docs/plan.md"})
    assert "front" not in plain and pointer.current() is None
    off = _call(files_h, {"target": "ses_cloude_a", "path": "docs/plan.md", "front": False})
    assert "front" not in off and pointer.current() is None
    nowhere = _call(files_h, {"target": "ses_cloude_a", "path": "docs/plan.md", "front": True})
    assert nowhere["file"]["path"] == "docs/plan.md" and nowhere["front"]["shown"] is False and nowhere["front"]["reason"] == "no_window"
    assert pointer.current() is None


def test_browser_open_front_shows_the_page_row_in_the_window_used_last(browser_h, monkeypatch):
    monkeypatch.setattr(pointer.resource_push, "notify", lambda topic: None)
    last_window.reset_for_test()
    pointer.reset_for_test()
    handler = tools._TOOLS["browser_open"][3]
    args = {"url": "/static/popout.html?tab=flow&item=395"}
    plain = json.loads(asyncio.run(handler(SimpleNamespace(app=browser_h.app), None, dict(args)))["content"][0]["text"])
    assert "front" not in plain and pointer.current() is None
    nowhere = json.loads(asyncio.run(handler(SimpleNamespace(app=browser_h.app), None, {**args, "front": True}))["content"][0]["text"])
    assert nowhere["front"] == {"shown": False, "reason": "no_window", "detail": nowhere["front"]["detail"]} and nowhere["page"]["id"]
    last_window.touch(ME)
    done = json.loads(asyncio.run(handler(SimpleNamespace(app=browser_h.app), None, {**args, "front": True}))["content"][0]["text"])
    assert done["front"]["shown"] is True
    assert pointer.current()["id"] == done["page"]["id"] and pointer.current()["kind"] == "browser"
    last_window.reset_for_test()
    pointer.reset_for_test()


def test_both_open_tools_declare_front_as_an_optional_boolean():
    for name in ("files_open", "browser_open"):
        schema = tools._TOOLS[name][1]["front"]
        assert schema["type"] == "boolean" and schema["default"] is False
        assert "front" not in tools._TOOLS[name][2]



def _sidebar(app, args: dict, caller=PANE) -> dict:
    handler = tools._TOOLS["sidebar_show"][3]
    return json.loads(asyncio.run(handler(SimpleNamespace(app=app), caller, args))["content"][0]["text"])


def test_sidebar_show_is_an_arrange_write_with_its_own_arguments():
    assert "sidebar_show" in tools.WRITE_TOOLS and "sidebar_show" in tools._UNGATED_WRITES
    _desc, schema, required, _handler = tools._TOOLS["sidebar_show"]
    assert set(schema) == {"kind", "id"} and required == ["kind"] and schema["kind"]["enum"] == list(KINDS)


def test_sidebar_show_reaches_the_route(ui):
    _active(ui)
    row = _file_row()
    answer = _sidebar(ui.app, {"kind": "file", "id": row})
    assert answer["shown"] is True and answer["id"] == row and pointer.current()["target_client_id"] == ME


def test_sidebar_show_refusals_read_as_tool_errors(ui):
    with pytest.raises(ToolError, match="no window has been used"):
        _sidebar(ui.app, {"kind": "task_manager"})
    _active(ui)
    with pytest.raises(ToolError, match="no open file row"):
        _sidebar(ui.app, {"kind": "file", "id": "0123456789abcdef"})
    with pytest.raises(ToolError, match="does not take"):
        _sidebar(ui.app, {"kind": "task_manager", "extra": 1})
    with pytest.raises(ToolError):
        _sidebar(ui.app, {"kind": "dashboard"})


def test_an_external_token_s_show_waits_in_the_owner_s_inbox_class():
    assert "sidebar_show" in tools._UNGATED_WRITES
    assert AgentCaller("mcp-token:1", "mcp-token:1", "mcp-token:1", token_name="laptop").token_name == "laptop"


def test_board_with_the_review_board_plugin_off_is_not_found(ui, monkeypatch):
    from src.cplugs.sdk import board_pages

    _active(ui)
    monkeypatch.setattr(board_pages, "get", lambda: None)
    res = _show(ui, kind="board", id="any-board")
    assert res.status_code == 404 and "review board plugin is off" in str(res.json()["detail"])


def test_board_resolves_through_the_registered_port(ui, monkeypatch):
    from src.cplugs.reviewboard import pages_port
    from src.cplugs.sdk import ports

    _active(ui)
    pages_port.register()
    try:
        res = _show(ui, kind="board", id="any-board")
    finally:
        ports.unregister(pages_port.board_pages.PORT)
    assert res.status_code == 404 and "not open as a page row" in str(res.json()["detail"])
