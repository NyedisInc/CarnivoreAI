
from __future__ import annotations

import asyncio
from contextlib import closing

import pytest

from tests.python.companies.conftest import client, world  # noqa: F401
from src.core.db import connect
from src.core.mcp import beast_mode, pending, tools
from src.core.mcp.approvals import call_context
from src.core.mcp.caller import AgentCaller
from src.core.project_colors.color_math import oklch_hue_of

PANE = AgentCaller("ses_a", "cloude_a", "ses_a")
READ_ONLY = AgentCaller("ses_a", "cloude_a", "ses_a", scope="read")
NAMES = ("company_color_set", "session_group_color_set", "layout_color_set")


class View:

    gate_waited = False


@pytest.fixture()
def gate(monkeypatch):
    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    monkeypatch.setattr(pending, "MAX_WAIT_SECONDS", 0.05)


def _call(name, args, caller=PANE):
    return asyncio.run(tools.call_tool(View(), caller, name, args))


def test_registered_with_schema_hidden_from_read_scope_and_gated_as_designed():
    for name in NAMES:
        assert name in tools.WRITE_TOOLS
        assert name not in {t["name"] for t in tools.tool_definitions(READ_ONLY)}
        props = next(t for t in tools.tool_definitions(PANE) if t["name"] == name)["inputSchema"]["properties"]
        assert "color" in props
    assert "company_color_set" in call_context.GATED_TOOLS
    assert "company_color_set" not in beast_mode.ALWAYS_WAITS
    assert "session_group_color_set" not in call_context.GATED_TOOLS and "layout_color_set" not in call_context.GATED_TOOLS


def test_bad_arguments_are_refused_before_anything_is_filed(gate):
    bad = (
        ("company_color_set", {"company_id": 1, "color": "teal"}),
        ("company_color_set", {"company_id": 1, "color": "#12345"}),
        ("company_color_set", {"company_id": 0, "color": "#6c799f"}),
        ("company_color_set", {"company_id": 1, "color": "#6c799f", "hue": 3}),
        ("session_group_color_set", {"group": "g", "color": "red"}),
        ("layout_color_set", {"layout": " ", "color": "#6c799f"}),
        ("layout_color_set", {"layout": "u", "color": "#6c799f", "extra": 1}),
    )
    for name, args in bad:
        assert _call(name, args)["isError"] is True, (name, args)
    assert not pending.get_store().list()


def test_company_color_waits_for_approval_then_stores_the_hue(world, gate):  # noqa: F811
    from src.core.companies import store

    with closing(connect(world.db, create=False)) as conn:
        company = store.create_company(conn, "Acme")["id"]
    assert "pending" in str(_call("company_color_set", {"company_id": company, "color": "#6C799F"}))
    asyncio.run(pending.get_store().approve(pending.get_store().list()[0]["id"]))
    with closing(connect(world.db, create=False)) as conn:
        assert store.get_company(conn, company)["hue"] == oklch_hue_of("#6c799f")
