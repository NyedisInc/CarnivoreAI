
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from src.api import row_looks_routes
from src.core import row_looks
from src.core.mcp import tools
from src.core.mcp.common import ToolError
from src.core.open_files import open_list
from src.core.resource_push.topics import ROW_LOOKS
from src.core.row_looks.palette import COLORS, ICONS
from tests.python.open_files.test_files_open_tool import PANE, _call, h  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def pushed(monkeypatch, tmp_path):
    names: list = []
    monkeypatch.setattr(row_looks.registry.resource_push, "notify", names.append)
    row_looks.reset_for_test()
    row_looks.configure(tmp_path)
    yield names
    row_looks.reset_for_test()


def _tool(h, name: str, args: dict, caller=PANE) -> dict:
    result = asyncio.run(tools._TOOLS[name][3](h.manager, caller, args))
    return json.loads(result["content"][0]["text"])


def test_files_open_styles_the_row_and_default_is_unstyled(h, pushed):
    plain = _call(h, {"target": "ses_cloude_a", "path": "docs/plan.md"})
    assert row_looks.listing() == {}
    styled = _call(h, {"target": "ses_cloude_a", "path": "docs/plan.md", "color": "cyan", "icon": "docs"})
    assert styled["file"]["id"] == plain["file"]["id"]
    assert row_looks.listing() == {plain["file"]["id"]: row_looks.Look("cyan", "docs")}
    assert ROW_LOOKS in pushed


@pytest.mark.parametrize("args,needle", [({"color": "#ff0000"}, "valid colors"), ({"color": "magenta"}, "valid colors"),
                                         ({"icon": "nope"}, "valid icons: docs")])
def test_an_unknown_look_is_refused_with_the_valid_names(h, pushed, args, needle):
    with pytest.raises(ToolError, match=needle):
        _call(h, {"target": "ses_cloude_a", "path": "docs/plan.md", **args})
    assert open_list.listing(None) == [] and row_looks.listing() == {}


def test_restyle_an_open_row_then_clear_it(h, pushed):
    row = _call(h, {"target": "ses_cloude_a", "path": "docs/plan.md", "color": "cyan"})["file"]["id"]
    done = _tool(h, "sidebar_row_look_set", {"row": row, "icon": "star"})
    assert (done["color"], done["icon"]) == ("cyan", "star")
    done = _tool(h, "sidebar_row_look_set", {"row": row, "color": None})
    assert (done["color"], done["icon"]) == (None, "star")
    _tool(h, "sidebar_row_look_set", {"row": row, "icon": None})
    assert row_looks.listing() == {}


def test_restyle_refusals(h, pushed):
    with pytest.raises(ToolError, match="no open file"):
        _tool(h, "sidebar_row_look_set", {"row": "0" * 16, "color": "cyan"})
    row = _call(h, {"target": "ses_cloude_a", "path": "docs/plan.md"})["file"]["id"]
    with pytest.raises(ToolError, match="send color, icon or both"):
        _tool(h, "sidebar_row_look_set", {"row": row})
    with pytest.raises(ToolError, match="valid colors"):
        _tool(h, "sidebar_row_look_set", {"row": row, "color": "#00ff00"})
    assert row_looks.listing() == {}


def test_closing_a_row_forgets_its_look(h, pushed):
    row = _call(h, {"target": "ses_cloude_a", "path": "docs/plan.md", "icon": "bolt"})["file"]["id"]
    assert open_list.close(row)
    assert row_looks.listing() == {}


def test_the_looks_survive_a_restart(h, pushed, tmp_path):
    row = _call(h, {"target": "ses_cloude_a", "path": "docs/plan.md", "color": "coral"})["file"]["id"]
    row_looks.configure(tmp_path)
    assert row_looks.listing()[row].color == "coral"


def test_get_route_lists_every_look(h, pushed):
    row = _call(h, {"target": "ses_cloude_a", "path": "docs/plan.md", "color": "green", "icon": "code"})["file"]["id"]
    answer = asyncio.run(row_looks_routes.list_row_looks())
    assert answer.looks[row].model_dump() == {"color": "green", "icon": "code"}


def test_a_browser_session_row_can_be_styled_and_forgotten(pushed, monkeypatch):
    from types import SimpleNamespace

    from fastapi import HTTPException

    from src.api import browser_routes
    from src.models.row_looks import RowLookRequest

    live = "ab" * 8

    async def row_or_404(_manager, browser_id):
        if browser_id != live:
            raise HTTPException(status_code=404, detail="no such browser session")

    monkeypatch.setattr(browser_routes, "_row_or_404", row_or_404)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(browser_manager=object())))
    done = asyncio.run(row_looks_routes.set_row_look(live, RowLookRequest(color="violet"), request))
    assert (done.color, done.icon) == ("violet", None) and ROW_LOOKS in pushed
    with pytest.raises(HTTPException) as gone:
        asyncio.run(row_looks_routes.set_row_look("cd" * 8, RowLookRequest(color="violet"), request))
    assert gone.value.status_code == 404
    row_looks.forget(live)
    assert row_looks.listing() == {}


def test_the_tool_is_an_arrange_write():
    assert "sidebar_row_look_set" in tools.WRITE_TOOLS and "sidebar_row_look_set" in tools._UNGATED_WRITES


def test_browser_open_takes_a_look_and_refuses_an_unknown_one():
    from src.core.mcp.browser_open_tools import _body

    body = _body({"url": "https://example.com", "color": "violet", "icon": "globe"})
    assert (body.color, body.icon) == ("violet", "globe")
    with pytest.raises(ToolError, match="valid icons"):
        _body({"url": "https://example.com", "icon": "nope"})
    with pytest.raises(ToolError, match="valid colors"):
        _body({"url": "https://example.com", "color": "#123456"})


def test_icon_list_matches_the_client_and_icons_ts():
    client = (ROOT / "web/src/lib/open-files/row-looks.ts").read_text()
    listed = tuple(re.findall(r"'([a-z-]+)'", client.split("ROW_ICONS", 1)[1].split("] as const", 1)[0]))
    assert listed == ICONS
    colors = tuple(re.findall(r"'([a-z-]+)'", client.split("ROW_COLORS", 1)[1].split("] as const", 1)[0]))
    assert colors == COLORS
    icons_ts = (ROOT / "web/src/opscenter/ui/icons.ts").read_text()
    assert [n for n in ICONS if not re.search(rf'^\s*"{re.escape(n)}":', icons_ts, re.M)] == []
