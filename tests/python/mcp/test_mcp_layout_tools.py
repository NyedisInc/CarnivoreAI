
from __future__ import annotations

import asyncio
import json
from contextlib import closing
from types import SimpleNamespace

from tests.python.mcp.test_mcp_session_groups import PANE, READ_ONLY, View, world  # noqa: F401
from src.core.db import connect
from src.core.mcp import tools
from tests.layouts_helpers import grid, row

NAMES = ("cloude_a", "cloude_b", "cloude_c")


def _call(view, name, args, caller=PANE):
    return asyncio.run(tools.call_tool(view, caller, name, args))


def _body(answer: dict) -> dict:
    return json.loads(answer["content"][0]["text"])


def _setup(world, monkeypatch):
    db, view, _ = world
    uuids, ids = {}, {}
    with closing(connect(db, create=False)) as conn, conn:
        for n in NAMES:
            uuids[n] = f"uuid-{n}"
            ids[n] = conn.execute(
                "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, origin, lifecycle, "
                "created_at, updated_at) VALUES (?, 'cloude', ?, 1, 'created', 'running', "
                "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')", (uuids[n], n)).lastrowid

    async def infos(self):
        return [SimpleNamespace(tmux_session=n, host_key="local", session=SimpleNamespace(id=f"ses_{n}"),
                                session_row_id=ids[n], session_uuid=uuids[n], label=None, claude_title=None,
                                agent_family=None, agent_type=None) for n in NAMES]

    monkeypatch.setattr(View, "list_infos", infos)
    from src.api import layouts_routes as routes
    from src.models.layouts import CreateLayoutRequest

    made = asyncio.run(routes.create_layout(
        CreateLayoutRequest(name="Working", shape=grid(row(ids["cloude_a"]), row(ids["cloude_b"]))),
        SimpleNamespace(app=view.app)))
    return view, made.layout.layout_uuid, uuids


def test_registered_and_write_tools_hidden_from_read_scope():
    for name in ("layouts_list", "layout_member_add", "layout_member_remove"):
        assert name in tools._TOOLS
    shown = {t["name"] for t in tools.tool_definitions(READ_ONLY)}
    assert "layouts_list" in shown
    assert not shown & {"layout_member_add", "layout_member_remove"}


def test_add_then_remove_by_tmux_name_and_id(world, monkeypatch):
    view, layout, uuids = _setup(world, monkeypatch)
    listed = _body(_call(view, "layouts_list", {}))
    assert [m["name"] for m in listed["layouts"][0]["members"]] == ["cloude_a", "cloude_b"]
    added = _call(view, "layout_member_add", {"layout": "working", "session": "cloude_c"})
    assert not added.get("isError"), added
    assert _body(added)["status"] == "added"
    assert uuids["cloude_c"] in {m["session_uuid"] for m in _body(added)["layout"]["members"]}
    again = _body(_call(view, "layout_member_add", {"layout": layout, "session": "ses_cloude_c"}))
    assert again["status"] == "already_present"
    gone = _body(_call(view, "layout_member_remove", {"layout": layout, "session": "cloude_c"}))
    assert gone["status"] == "removed" and not gone["deleted"]
    assert _body(_call(view, "layout_member_remove", {"layout": layout, "session": "cloude_c"}))["status"] == "not_a_member"


def test_refusals(world, monkeypatch):
    view, layout, _ = _setup(world, monkeypatch)
    for args in ({"layout": "nope", "session": "cloude_c"}, {"layout": layout, "session": "no-such-agent-xyz"},
                 {"layout": layout}, {"layout": layout, "session": "cloude_c", "x": 1},
                 {"layout": layout, "session": "cloude_c", "expected_revision": 99}):
        assert _call(view, "layout_member_add", args)["isError"] is True, args


def test_remove_from_two_member_layout_is_refused(world, monkeypatch):
    view, layout, _ = _setup(world, monkeypatch)
    refused = _call(view, "layout_member_remove", {"layout": layout, "session": "cloude_a"})
    assert refused["isError"] is True
    assert len(_body(_call(view, "layouts_list", {}))["layouts"][0]["members"]) == 2
