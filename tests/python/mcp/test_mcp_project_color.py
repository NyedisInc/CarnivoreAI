
from __future__ import annotations

import asyncio
import json
from contextlib import closing

import pytest

from tests.python.companies.conftest import client, world  # noqa: F401
from src.core.db import connect
from src.core.mcp import pending, tools
from src.core.mcp.approvals import call_context
from src.core.mcp.caller import AgentCaller
from src.core.project_colors.palette import SOFT_PALETTE

PANE = AgentCaller("ses_a", "cloude_a", "ses_a")
READ_ONLY = AgentCaller("ses_a", "cloude_a", "ses_a", scope="read")


class View:

    gate_waited = False


@pytest.fixture()
def gate(monkeypatch):
    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    monkeypatch.setattr(pending, "MAX_WAIT_SECONDS", 0.05)


def _call(args, caller=PANE):
    return asyncio.run(tools.call_tool(View(), caller, "project_color_set", args))


def _approve():
    asyncio.run(pending.get_store().approve(pending.get_store().list()[0]["id"]))


def _colors(world):  # noqa: F811
    with closing(connect(world.db, create=False)) as conn:
        return dict(conn.execute("SELECT display_name, color FROM projects").fetchall())


def test_registered_gated_with_schema_and_hidden_from_read_scope():
    assert "project_color_set" in tools.WRITE_TOOLS
    assert "project_color_set" in call_context.GATED_TOOLS
    definition = next(t for t in tools.tool_definitions(PANE) if t["name"] == "project_color_set")
    props = definition["inputSchema"]["properties"]
    assert set(props) == {"project", "color", "colors"}
    assert "project_color_set" not in {t["name"] for t in tools.tool_definitions(READ_ONLY)}
    assert _call({"project": 1, "color": SOFT_PALETTE[0]}, READ_ONLY)["isError"] is True


def test_single_waits_for_approval_then_patches_through_the_route(world, gate):  # noqa: F811
    before = _colors(world)
    assert "pending" in str(_call({"project": world.ids["alpha"], "color": "#C17B87"}))
    assert _colors(world) == before
    _approve()
    assert _colors(world)["alpha"] == "#c17b87"
    assert _colors(world)["beta"] == before["beta"]


def test_bulk_by_name_and_id_is_one_approval(world, gate):  # noqa: F811
    _call({"colors": {"alpha": SOFT_PALETTE[1], str(world.ids["beta"]): SOFT_PALETTE[2]}})
    assert len(pending.get_store().list()) == 1
    _approve()
    got = _colors(world)
    assert (got["alpha"], got["beta"]) == (SOFT_PALETTE[1], SOFT_PALETTE[2])


def test_invalid_hex_unknown_project_and_bad_shapes_refuse_all_before_filing(world, gate):  # noqa: F811
    before = _colors(world)
    bad = (
        {"project": world.ids["alpha"], "color": "orange"},
        {"project": world.ids["alpha"], "color": "#12345"},
        {"project": 9999, "color": SOFT_PALETTE[0]},
        {"colors": {"alpha": SOFT_PALETTE[0], "beta": "#zzzzzz"}},
        {"colors": {"alpha": SOFT_PALETTE[0], "no-such-project": SOFT_PALETTE[1]}},
        {"colors": {}},
        {"colors": {"alpha": SOFT_PALETTE[0]}, "project": world.ids["alpha"]},
        {"project": world.ids["alpha"], "color": SOFT_PALETTE[0], "extra": 1},
    )
    for args in bad:
        assert _call(args)["isError"] is True, args
    assert not pending.get_store().list()
    assert _colors(world) == before


def test_an_empty_color_removes_it_in_the_single_and_the_bulk_form(world, gate):  # noqa: F811
    _call({"colors": {"alpha": SOFT_PALETTE[1], "beta": SOFT_PALETTE[2]}})
    _approve()
    assert _colors(world) == {"alpha": SOFT_PALETTE[1], "beta": SOFT_PALETTE[2]}
    _call({"project": world.ids["alpha"], "color": ""})
    assert pending.get_store().list()[0]["args_summary"].startswith("remove the color of 1 project")
    _approve()
    assert _colors(world) == {"alpha": None, "beta": SOFT_PALETTE[2]}
    _call({"colors": {"alpha": SOFT_PALETTE[0], "beta": ""}})
    assert pending.get_store().list()[0]["args_summary"].startswith("set the color of 2 projects")
    _approve()
    assert _colors(world) == {"alpha": SOFT_PALETTE[0], "beta": None}
