
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.responses import JSONResponse

from src.core.mcp import beast_mode, project_library_tools, tool_switches, tools
from tests.python.beast_mode.grid import arm as arm_beast
from tests.python.mcp.test_mcp_route_adapters import EXTERNAL, PANE, READ_ONLY, View, world  # noqa: F401

SPECS = project_library_tools.SPECS
NAMES = [s.name for s in SPECS] + ["project_merge_run"]
SECRET = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
READS = {"projects_authority_get", "projects_presence_get", "project_history_get", "project_storage_get", "project_root_check",
         "company_accounts_get", "item_settings_list", "row_looks_list"}


def _call(name: str, args: dict, caller=PANE) -> dict:
    return asyncio.run(tools.call_tool(View(), caller, name, args))


def _record(monkeypatch, route: str, answer=None) -> list:
    seen: list = []
    module, name = route.split(":")

    async def recorder(*args, **kwargs):
        seen.append((args, kwargs))
        return answer if answer is not None else {"ok": True}

    monkeypatch.setattr(f"{module}.{name}", recorder)
    return seen


def test_eight_reads_run_for_a_read_token_and_the_writes_do_not(world):
    listed = {d["name"] for d in tools.tool_definitions(READ_ONLY)}
    assert READS <= listed and set(NAMES) - READS <= set(tools.WRITE_TOOLS)
    for name in sorted(READS):
        spec = next(s for s in SPECS if s.name == name)
        assert not _call(name, dict(spec.example), READ_ONLY).get("isError"), name
    for name in set(NAMES) - READS:
        assert name in tools.WRITE_TOOLS and name not in listed and _call(name, {}, READ_ONLY)["isError"] is True


def test_history_passes_every_query_parameter_as_a_plain_value(monkeypatch, world):
    seen = _record(monkeypatch, "src.api.projects_history_routes:get_projects_history")
    _call("project_history_get", {"q": "carn", "limit": 7, "include_automated": True})
    (_, kw), = seen
    assert (kw["q"], kw["limit"], kw["include_automated"]) == ("carn", 7, True)
    assert (kw["offset"], kw["session_limit"], kw["project_state"], kw["sort"], kw["include_empty"]) == (0, 10, "all", "recent", True)
    assert kw["state"] is None and kw["since"] is None and kw["offloaded"] is False and kw["include_conversations"] is False


@pytest.mark.parametrize("name,args", [
    ("project_history_get", {"limit": 0}), ("project_history_get", {"limit": 101}), ("project_history_get", {"offset": -1}),
    ("project_history_get", {"session_limit": 501}), ("project_history_get", {"sort": "newest"}),
    ("project_history_get", {"project_state": "x"}), ("project_history_get", {"include_empty": "yes"}),
    ("project_history_get", {"q": 5}), ("project_history_get", {"limit": True}),
    ("project_storage_get", {"project": 0}), ("project_storage_get", {"project": "x"}),
    ("project_storage_check", {"project": True}), ("project_root_check", {"path": ""}), ("project_root_check", {"path": 5}),
    ("company_accounts_get", {"company_id": 0}), ("company_accounts_set", {"company_id": 1, "accounts": "github"}),
    ("company_accounts_set", {"company_id": "x", "accounts": {}}), ("session_group_icon_set", {"group": "g"}),
    ("session_group_icon_set", {"group": "g", "icon": 5}), ("session_group_rule_set", {"group": "g", "flags": "running"}),
    ("session_group_rule_set", {"group": "g", "prefix": 5}), ("project_merge_run", {"source": 3, "into": 3}),
    ("project_merge_run", {"source": 3}), ("project_merge_run", {"source": 3, "into": 4, "allow_different_folder": True}),
    ("projects_authority_get", {"extra": 1}),
])
def test_a_bad_argument_is_refused_before_any_route_runs(world, name, args):
    assert _call(name, args)["isError"] is True and world == []


def test_storage_reads_resolve_the_project_id_to_its_name(monkeypatch, world):
    got = _record(monkeypatch, "src.api.project_pack_routes:get_project_storage")
    _call("project_storage_get", {"project": 4})
    assert got[0][0] == ("demo",)


def test_check_root_refusal_is_the_tools_error_with_the_routes_detail(monkeypatch, world):
    async def refuse(body):
        return JSONResponse(status_code=409, content={"detail": "that folder holds live projects", "code": "project_root_refused"})

    monkeypatch.setattr("src.api.projects_routes.check_project_root", refuse)
    text = json.dumps(_call("project_root_check", {"path": "/tmp/x"}))
    assert "409" in text and "project_root_refused" in text and "holds live projects" in text


def test_a_route_refusal_reads_as_a_tool_error(monkeypatch, world):
    from fastapi import HTTPException

    async def missing(company_id):
        raise HTTPException(404, detail="Company '9' not found")

    monkeypatch.setattr("src.api.companies_routes.get_company_accounts", missing)
    answer = _call("company_accounts_get", {"company_id": 9})
    assert answer["isError"] is True and "404" in json.dumps(answer)


@pytest.mark.parametrize("name", sorted(READS))
def test_every_read_answer_is_redacted_and_keeps_its_keys(monkeypatch, world, name):
    spec = next(s for s in SPECS if s.name == name)

    async def route(*args, **kwargs):
        return {"project_count": 3, "message": f"token {SECRET}"}

    module, fn = spec.route.split(":")
    monkeypatch.setattr(f"{module}.{fn}", route)
    text = json.dumps(_call(name, dict(spec.example)))
    assert SECRET not in text and "project_count" in text


def test_company_accounts_set_waits_even_in_beast_mode_and_passes_the_body_model(monkeypatch, world):
    arm_beast(monkeypatch, lambda: True)
    answer = _call("company_accounts_set", {"company_id": 2, "accounts": {"github": "acme"}})
    assert "company_accounts_set" in beast_mode.ALWAYS_WAITS and json.loads(answer["content"][0]["text"])["status"] == "pending"
    assert world == []


def test_project_merge_waits_even_in_beast_mode_for_every_caller(monkeypatch, world):
    arm_beast(monkeypatch, lambda: True)
    for caller in (PANE, EXTERNAL):
        answer = _call("project_merge_run", {"source": 3, "into": 4}, caller)
        assert json.loads(answer["content"][0]["text"])["status"] == "pending"
    assert "project_merge_run" in beast_mode.ALWAYS_WAITS and world == []


def test_project_merge_calls_the_route_without_the_different_folder_flag(monkeypatch):
    from src.core.mcp import write_tools

    seen: list = []

    async def merge(source_id, body, request):
        seen.append((source_id, body.into, body.allow_different_folder))
        return {"sessions_moved": 2}

    async def go(manager, caller, target_id, target_tmux, action, summary, args, run, **kw):
        assert action == "project_merge_run" and "MERGE" in summary
        return await run(True)

    monkeypatch.setattr("src.api.library_cleanup_routes.merge_project", merge)
    monkeypatch.setattr(write_tools, "park", go)
    monkeypatch.setattr(project_library_tools.ra, "route_request", lambda manager: SimpleNamespace(app=None))
    answer = asyncio.run(project_library_tools.project_merge_run(object(), PANE, {"source": 3, "into": 4}))
    assert seen == [(3, 4, False)] and "sessions_moved" in json.dumps(answer)


def test_group_tools_resolve_a_name_and_are_arrange_writes(monkeypatch, world):
    icon = _record(monkeypatch, "src.api.session_group_icon_routes:set_session_group_icon")
    rule = _record(monkeypatch, "src.api.session_group_rule_routes:set_session_group_rule")
    assert {"session_group_icon_set", "session_group_rule_set"} <= tools._UNGATED_WRITES
    _call("session_group_icon_set", {"group": "G", "icon": "flask"})
    _call("session_group_rule_set", {"group": "g", "flags": ["running"], "prefix": "api"})
    assert icon[0][0][0] == "g" and icon[0][0][1].icon == "flask"
    assert rule[0][0][1].flags == ["running"] and rule[0][0][1].prefix == "api" and rule[0][0][1].suffix is None
    held = _call("session_group_icon_set", {"group": "g", "icon": None}, EXTERNAL)
    assert "pending" in str(held) and len(icon) == 1


def test_the_rare_tools_ship_switched_off_and_history_stays_on() -> None:
    off = {n for n in NAMES if n in tool_switches.RARELY_USED}
    assert set(NAMES) - off == {"project_history_get"} and len(NAMES) == 13
    assert tool_switches.RARELY_USED <= set(tools.tool_names())


def _parked_rows() -> list:
    from src.core.mcp import pending

    return pending.get_store().list() if hasattr(pending.get_store(), "list") else []


@pytest.mark.parametrize("accounts", [
    {"github": "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8", "token": "x"},
    {"github": "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"},
    {"aws": "123", "extra": "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"},
])
def test_a_secret_or_unknown_pointer_is_refused_before_anything_is_parked(monkeypatch, world, accounts):
    arm_beast(monkeypatch, lambda: False)
    answer = _call("company_accounts_set", {"company_id": 2, "accounts": accounts}, EXTERNAL)
    text = json.dumps(answer)
    assert answer["isError"] is True and world == [] and "pending" not in text
    assert "ghp_" not in text and "a1B2c3D4" not in text and _parked_rows() == []


def test_check_root_error_text_is_redacted(monkeypatch, world):
    async def refuse(body):
        return JSONResponse(status_code=409, content={"detail": f"bad {SECRET}", "code": "project_root_refused"})

    monkeypatch.setattr("src.api.projects_routes.check_project_root", refuse)
    text = json.dumps(_call("project_root_check", {"path": "/tmp/x"}))
    assert SECRET not in text and "project_root_refused" in text
