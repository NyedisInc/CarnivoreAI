
from __future__ import annotations

import asyncio
import json
from contextlib import closing

import pytest

from tests.python.companies.conftest import client, world  # noqa: F401
from src.core.companies import store
from src.core.db import connect
from src.core.mcp import pending, tools
from src.core.mcp.caller import AgentCaller

PANE = AgentCaller("ses_a", "cloude_a", "ses_a")
READ_ONLY = AgentCaller("ses_a", "cloude_a", "ses_a", scope="read")


class View:

    gate_waited = False


@pytest.fixture()
def gate(monkeypatch):
    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    monkeypatch.setattr(pending, "MAX_WAIT_SECONDS", 0.05)


def _call(name, args, caller=PANE):
    return asyncio.run(tools.call_tool(View(), caller, name, args))


def _payload(answer) -> dict:
    return json.loads(answer["content"][0]["text"])


def _company_of(world, name):  # noqa: F811
    with closing(connect(world.db, create=False)) as conn:
        return conn.execute("SELECT company_id FROM projects WHERE display_name = ?", (name,)).fetchone()[0]


def test_reads_carry_company_fields(world, gate):  # noqa: F811
    with closing(connect(world.db)) as conn:
        company = store.create_company(conn, "Acme")
        store.assign_project(conn, world.ids["alpha"], company["id"])
    assert _company_of(world, "alpha") == company["id"]
    projects = _payload(_call("projects_list", {}))["projects"]
    assert {(p["name"], p["company_name"]) for p in projects} >= {("alpha", "Acme"), ("beta", None)}
    assert _payload(_call("companies_list", {}))["companies"] == [{"id": company["id"], "name": "Acme", "project_count": 1, "hue": None, "parent_id": None, "hq_project_id": None}]
    names = {t["name"] for t in tools.tool_definitions(READ_ONLY)}
    assert "companies_list" in names and "company_hue_set" not in names


def test_approval_summaries_name_the_company_and_project_not_ids(world, gate):  # noqa: F811
    with closing(connect(world.db)) as conn:
        company = store.create_company(conn, "Acme")
    _call("company_hq_set", {"company_id": company["id"], "project_id": world.ids["beta"]})
    _call("company_hq_set", {"company_id": 4242, "project_id": world.ids["beta"]})
    joined = "\n".join(str(a["args_summary"]) for a in pending.get_store().list())
    assert 'make "beta" (project) the HQ project of "Acme"' in joined
    assert "company 4242" in joined


def test_company_batch_route_reports_each_project_and_never_skips_silently(world, client):  # noqa: F811
    with closing(connect(world.db)) as conn:
        company = store.create_company(conn, "Acme")
    ids = [world.ids["alpha"], 9999, world.ids["beta"]]
    body = client.put("/api/v1/projects/company", json={"project_ids": ids, "company_id": company["id"]}).json()
    assert (body["filed"], body["failed"]) == (2, 1)
    assert [(r["project_id"], r["ok"]) for r in body["results"]] == [(ids[0], True), (9999, False), (ids[2], True)]
    assert body["results"][1]["error"] and body["results"][0]["name"] == "alpha"
    assert _company_of(world, "alpha") == _company_of(world, "beta") == company["id"]
    assert client.put("/api/v1/projects/company", json={"project_ids": ids[:1], "company_id": 4242}).status_code == 404
    assert client.put("/api/v1/projects/company", json={"project_ids": [ids[0], ids[0]], "company_id": None}).status_code == 422
    assert client.put("/api/v1/projects/company", json={"project_ids": [], "company_id": None}).status_code == 422
