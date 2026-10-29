
from __future__ import annotations

import asyncio
from contextlib import closing

from tests.python.companies.conftest import world  # noqa: F401
from tests.python.mcp.test_mcp_companies import PANE, READ_ONLY, _call, _payload, gate  # noqa: F401
from src.core.db import connect
from src.core.mcp import pending, tools
from src.core.mcp.approvals.call_context import GATED_TOOLS
from src.core.project_writes import create_project

NEW_TOOLS = ("company_create", "company_rename", "company_parent_set", "company_hq_set", "company_delete")


def _approve_last() -> None:
    store = pending.get_store()
    asyncio.run(store.approve(store.list()[-1]["id"]))


def _companies() -> dict:
    return {c["name"]: c for c in _payload(_call("companies_list", {}))["companies"]}


def test_every_company_write_waits_then_goes_through_the_route(world, gate):  # noqa: F811
    assert "pending" in str(_call("company_create", {"name": "IMC"}))
    assert _companies() == {}
    _approve_last()
    imc = _companies()["IMC"]
    _call("company_create", {"name": "Amerifund", "parent_id": imc["id"]})
    _approve_last()
    amf = _companies()["Amerifund"]
    assert amf["parent_id"] == imc["id"]

    _call("company_rename", {"company_id": amf["id"], "name": "Amerifund LLC"})
    _approve_last()
    _call("company_parent_set", {"company_id": amf["id"], "parent_id": None})
    _approve_last()
    assert _companies()["Amerifund LLC"]["parent_id"] is None
    _call("company_parent_set", {"company_id": amf["id"], "parent_id": imc["id"]})
    _approve_last()
    _call("company_hq_set", {"company_id": amf["id"], "project_id": world.ids["alpha"]})
    _approve_last()
    assert _companies()["Amerifund LLC"]["hq_project_id"] == world.ids["alpha"]

    _call("company_parent_set", {"company_id": imc["id"], "parent_id": amf["id"]})
    _approve_last()
    assert _companies()["IMC"]["parent_id"] is None

    _call("company_delete", {"company_id": imc["id"]})
    _approve_last()
    assert set(_companies()) == {"Amerifund LLC"} and _companies()["Amerifund LLC"]["parent_id"] is None


def test_bad_arguments_never_park_and_read_scope_cannot_see_them(world, gate):  # noqa: F811
    for name, args in (("company_create", {}), ("company_create", {"name": " "}), ("company_create", {"name": "x" * 81}),
                       ("company_create", {"name": "a", "parent_id": 0}), ("company_create", {"name": "a", "extra": 1}),
                       ("company_rename", {"company_id": 1}), ("company_parent_set", {"company_id": 1}),
                       ("company_parent_set", {"company_id": 2, "parent_id": 2}), ("company_hq_set", {"company_id": 1}),
                       ("company_delete", {"company_id": True})):
        assert _call(name, args)["isError"] is True, (name, args)
    assert not pending.get_store().list()
    readable = {t["name"] for t in tools.tool_definitions(READ_ONLY)}
    pane = {t["name"] for t in tools.tool_definitions(PANE)}
    for name in NEW_TOOLS:
        assert name in GATED_TOOLS and name in tools.WRITE_TOOLS and name in pane and name not in readable
        assert _call(name, {"company_id": 1, "name": "x"}, READ_ONLY)["isError"] is True


def test_projects_list_carries_parent_project_id(world, gate, tmp_path):  # noqa: F811
    with closing(connect(world.db)) as conn:
        create_project(conn, name="alpha-support", path=str(tmp_path / "alpha" / "support"))
    rows = {p["name"]: p for p in _payload(_call("projects_list", {}))["projects"]}
    assert rows["alpha-support"]["parent_project_id"] == world.ids["alpha"]
    assert rows["beta"]["parent_project_id"] is None
