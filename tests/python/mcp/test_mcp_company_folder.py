
from __future__ import annotations

import asyncio

from tests.python.companies.conftest import world  # noqa: F401
from tests.python.mcp.test_mcp_companies import PANE, READ_ONLY, _call, _payload, gate  # noqa: F401
from src.core.mcp import pending, tools
from src.core.mcp.approvals.call_context import GATED_TOOLS

NEW_TOOLS = ("company_folder_set", "project_company_set")


def _approve_last() -> None:
    store = pending.get_store()
    asyncio.run(store.approve(store.list()[-1]["id"]))


def _companies() -> dict:
    return {c["name"]: c for c in _payload(_call("companies_list", {}))["companies"]}


def _projects() -> dict:
    return {p["name"]: p for p in _payload(_call("projects_list", {}))["projects"]}


def test_folder_set_waits_then_stores_the_real_folder_and_clears(world, gate, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("HOME", str(tmp_path))
    folder = tmp_path / "Org" / "Acme" / "Globex"
    folder.mkdir(parents=True)
    _call("company_create", {"name": "Globex"})
    _approve_last()
    cid = _companies()["Globex"]["id"]
    assert _companies()["Globex"]["folder"] is None

    assert "pending" in str(_call("company_folder_set", {"company_id": cid, "folder": str(folder)}))
    assert _companies()["Globex"]["folder"] is None
    _approve_last()
    assert _companies()["Globex"]["folder"] == str(folder.resolve())

    _call("company_folder_set", {"company_id": cid, "folder": str(tmp_path / "missing")})
    _approve_last()
    assert _companies()["Globex"]["folder"] == str(folder.resolve())
    _call("company_folder_set", {"company_id": cid, "folder": None})
    _approve_last()
    assert _companies()["Globex"]["folder"] is None


def test_project_company_set_files_and_orphans(world, gate):  # noqa: F811
    _call("company_create", {"name": "Globex"})
    _approve_last()
    cid = _companies()["Globex"]["id"]
    pid = world.ids["alpha"]
    assert "pending" in str(_call("project_company_set", {"project": pid, "company_id": cid}))
    assert _projects()["alpha"]["company_id"] != cid
    _approve_last()
    assert _projects()["alpha"]["company_id"] == cid
    _call("project_company_set", {"project": pid, "company_id": None})
    _approve_last()
    assert _projects()["alpha"]["company_id"] is None


def test_bad_arguments_never_park_and_read_scope_cannot_see_them(world, gate):  # noqa: F811
    for name, args in (("company_folder_set", {"company_id": 1}), ("company_folder_set", {"company_id": 1, "folder": 5}),
                       ("company_folder_set", {"company_id": 1, "folder": " "}), ("company_folder_set", {"folder": "/x"}),
                       ("project_company_set", {"project": 1}), ("project_company_set", {"company_id": 1}),
                       ("project_company_set", {"project": 1, "company_id": 0}), ("project_company_set", {"project": 1, "company_id": 1, "x": 1})):
        assert _call(name, args)["isError"] is True, (name, args)
    assert not pending.get_store().list()
    readable = {t["name"] for t in tools.tool_definitions(READ_ONLY)}
    pane = {t["name"] for t in tools.tool_definitions(PANE)}
    for name in NEW_TOOLS:
        assert name in GATED_TOOLS and name in tools.WRITE_TOOLS and name in pane and name not in readable
