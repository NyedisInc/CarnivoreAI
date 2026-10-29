
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.api import open_files_routes
from src.core.crosstalk import directory
from src.core.db import db_path_for
from src.core.mcp import common, session_target, tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError
from src.core.open_files import open_list
from tests.python.open_files.test_open_files_routes import OTHER, SESSION, _add_session, ensure_db_migrated

PANE = AgentCaller("ses_cloude_a", "cloude_a", "ses_cloude_a")
EXTERNAL = AgentCaller("mcp-token:1", "mcp-token:1", "mcp-token:1", token_name="laptop")


@pytest.fixture
def h(tmp_path: Path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    project = tmp_path / "project"
    (project / "docs").mkdir(parents=True)
    (project / "docs" / "plan.md").write_text("# plan\n")
    _add_session(state, SESSION, str(project))
    _add_session(state, OTHER, str(project))
    live = SimpleNamespace(tmux_session="cloude_a", host_key="local", session_row_id=9, label=None, host_label="here",
                           session=SimpleNamespace(id="ses_cloude_a", working_dir=str(project), tmux_created_epoch=1))

    async def infos(_manager):
        return [live]

    monkeypatch.setattr(common, "_all_infos", infos)
    monkeypatch.setattr(session_target, "_session_uuid_of_row", lambda row_id: SESSION)
    monkeypatch.setattr(directory, "_asleep_rows", lambda: [{"id": 5, "session_uuid": OTHER, "tmux_name": "cloude_nap"}])
    monkeypatch.setattr(open_files_routes, "_db_path", lambda: db_path_for(state))
    monkeypatch.setattr(open_list.resource_push, "notify", lambda topic: None)
    open_list.reset_for_test()
    open_list.configure(state)
    yield SimpleNamespace(manager=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())))
    open_list.reset_for_test()


def _call(h, args: dict, caller: AgentCaller = PANE) -> dict:
    handler = tools._TOOLS["files_open"][3]
    result = asyncio.run(handler(h.manager, caller, args))
    return json.loads(result["content"][0]["text"])


def test_open_adds_a_row_and_a_second_call_reuses_it(h):
    first = _call(h, {"target": "ses_cloude_a", "path": "docs/plan.md"})
    assert first["reused"] is False and first["file"]["path"] == "docs/plan.md"
    assert first["file"]["session_uuid"] == SESSION and first["file"]["root"] == "workdir" and first["file"]["kind"] == "file"
    again = _call(h, {"target": "cloude_a", "path": "docs/plan.md"})
    assert again["reused"] is True and again["file"]["id"] == first["file"]["id"]
    assert [row.id for row in open_list.listing(None)] == [first["file"]["id"]]


def test_an_asleep_session_opens_from_its_session_uuid(h):
    result = _call(h, {"target": OTHER, "path": "docs/plan.md"})
    assert result["file"]["session_uuid"] == OTHER


@pytest.mark.parametrize("path", ["../x", "/etc/passwd", "docs/../../x"])
def test_a_path_outside_the_root_is_refused(h, path):
    with pytest.raises(ToolError, match="refused"):
        _call(h, {"target": "ses_cloude_a", "path": path})
    assert open_list.listing(None) == []


def test_a_missing_file_is_refused(h):
    with pytest.raises(ToolError, match="refused"):
        _call(h, {"target": "ses_cloude_a", "path": "docs/nope.md"})


def test_an_unknown_session_opens_nothing(h):
    with pytest.raises(ToolError, match="no live or asleep session"):
        _call(h, {"target": "ses_nobody", "path": "docs/plan.md"})
    assert open_list.listing(None) == []


def test_bad_arguments_are_refused(h):
    for args in ({"target": "ses_cloude_a"}, {"target": "ses_cloude_a", "path": "docs/plan.md", "root": "elsewhere"},
                 {"target": "ses_cloude_a", "path": "docs/plan.md", "extra": 1}):
        with pytest.raises(ToolError):
            _call(h, args)


def test_the_tool_is_an_arrange_write_that_an_external_token_parks(h):
    assert "files_open" in tools.WRITE_TOOLS and "files_open" in tools._UNGATED_WRITES
    assert set(tools._TOOLS["files_open"][1]) == {"target", "path", "root", "kind", "color", "icon", "front"}
