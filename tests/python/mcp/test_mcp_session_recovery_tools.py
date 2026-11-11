
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.core.mcp import beast_mode, pending, session_background_tools, session_recovery_tools, session_target, tools
from tests.python.beast_mode.grid import arm as arm_beast
from tests.python.mcp.test_mcp_route_adapters import (  # noqa: F401
    ASLEEP, EXTERNAL, PANE, READ_ONLY, View, world)

SPECS = session_recovery_tools.SPECS + session_background_tools.SPECS
NAMES = [s.name for s in SPECS]
UUID = "bbbbbbbb-2222-4222-8222-222222222222"
START = "Mon Sep 28 08:58:46 2026"
DESTRUCTIVE = {"session_external_stop"}
PLAIN_ACT = {"session_adopt", "session_recreate", "session_imported_restart", "session_background_job_stop", "session_background_jobs_stop"}
LEDGER = json.loads(Path(__file__).with_name("route_coverage_ledger.json").read_text())["routes"]


def _call(name: str, args: dict, caller=PANE) -> dict:
    return asyncio.run(tools.call_tool(View(), caller, name, args))


def _body(answer: dict) -> dict:
    return json.loads(answer["content"][0]["text"])


def _approve_all() -> None:
    store = pending.get_store()
    for item in store.list():
        asyncio.run(store.approve(item["id"]))


def test_the_destructive_tools_are_exactly_the_always_waits_ones():
    declared = session_recovery_tools.ALWAYS_WAIT_NAMES | session_background_tools.ALWAYS_WAIT_NAMES
    assert declared == DESTRUCTIVE
    assert DESTRUCTIVE <= beast_mode.ALWAYS_WAITS
    assert {n for n in NAMES if n in beast_mode.ALWAYS_WAITS} == DESTRUCTIVE
    assert all("always waits" in tools._TOOLS[n][0].lower() for n in DESTRUCTIVE)
    assert not PLAIN_ACT & beast_mode.ALWAYS_WAITS
    assert not any("always waits" in tools._TOOLS[n][0].lower() for n in PLAIN_ACT)


def test_reads_are_read_tokens_writes_are_not(world):
    reads = {s.name for s in SPECS if s.gate == "read"}
    assert len(reads) == 6
    listed = {d["name"] for d in tools.tool_definitions(READ_ONLY)}
    assert reads <= listed and not (set(NAMES) - reads) & listed
    for spec in SPECS:
        args = {"target": "cloude_b", **spec.example} if spec.reach else dict(spec.example)
        answer = _call(spec.name, args, READ_ONLY)
        assert bool(answer.get("isError")) == (spec.name not in reads), spec.name


@pytest.mark.parametrize("spec", [s for s in SPECS if s.reach], ids=lambda s: s.name)
def test_every_session_tool_resolves_its_target_through_session_target(world, monkeypatch, spec):
    seen: list = []
    real = session_target.TargetResolver.resolve

    async def spy(self, args, *, reach=session_target.LIVE, tool=""):
        seen.append((reach, tool))
        return await real(self, args, reach=reach, tool=tool)

    monkeypatch.setattr(session_target.TargetResolver, "resolve", spy)
    target = ASLEEP if spec.reach == session_target.CLOSED else "cloude_b"
    _call(spec.name, {"target": target, **spec.example})
    assert seen == [(spec.reach, spec.name)]


def test_query_defaults_are_never_passed_through(world):
    _call("session_records_list", {})
    _call("session_records_list", {"archived_only": True, "include_automated": True})
    _call("session_restart_preview", {"target": "cloude_b"})
    _call("session_recreate_preview", {"target": ASLEEP})
    _call("session_imported_restart_preview", {"session_uuid": UUID})
    seen = {c[0].split(":")[1]: c[1] for c in world}
    assert [(c[1][1:], c[2]) for c in world if c[0].endswith("list_session_records")] == [
        ((), {"include_automated": False, "archived_only": False}), ((), {"include_automated": True, "archived_only": True})]
    assert seen["restart_preview"][1:] == ("cloude_b",)
    assert seen["recreate_preview"] == (ASLEEP,)
    assert seen["imported_restart_preview"] == (UUID,)


def test_records_are_cut_to_the_limit_with_the_total(monkeypatch, world):
    async def many(request, **kwargs):
        return [{"session_uuid": f"u{i}"} for i in range(5)]

    monkeypatch.setattr("src.api.session_records_routes.list_session_records", many)
    answer = _body(_call("session_records_list", {"limit": 2}))
    assert answer["total"] == 5 and [r["session_uuid"] for r in answer["records"]] == ["u0", "u1"]


@pytest.mark.parametrize("name,args", [
    ("session_records_list", {"limit": 201}), ("session_records_list", {"archived_only": "yes"}),
    ("session_imported_restart_preview", {"session_uuid": "not-a-uuid"}),
    ("session_record_unarchive", {"session_uuid": 5}),
    ("session_background_set", {"target": "cloude_b", "dim": "dark"}), ("session_background_set", {"target": "cloude_b", "dim": True}),
    ("session_background_set", {"target": "cloude_b", "theme_id": 3}), ("session_background_set", {"target": "cloude_b", "disabled": "no"}),
])
def test_a_bad_argument_is_refused_before_any_route_runs(world, name, args):
    assert _call(name, args)["isError"] is True and world == []


@pytest.mark.parametrize("name,args", [
    ("session_adopt", {"session_name": ""}), ("session_adopt", {"session_name": "remote:peer-1:x"}), ("session_adopt", {"session_name": 5}),
    ("session_external_stop", {"session_name": "x" * 201}), ("session_external_stop", {"session_name": "a", "confirm_name": "a"}),
    ("session_imported_restart", {"session_uuid": "nope", "agent_type": "claude"}),
    ("session_imported_restart", {"session_uuid": UUID, "agent_type": ""}),
    ("session_background_job_stop", {"target": "cloude_b", "pid": 0, "start": START}),
    ("session_background_job_stop", {"target": "cloude_b", "pid": True, "start": START}),
    ("session_background_job_stop", {"target": "cloude_b", "pid": 5, "start": "s" * 65}),
    ("session_background_jobs_stop", {"target": "cloude_b", "targets": []}),
    ("session_background_jobs_stop", {"target": "cloude_b", "targets": [{"pid": 5}]}),
    ("session_background_jobs_stop", {"target": "cloude_b", "targets": [{"pid": 5, "start": START}, {"pid": 5, "start": START}]}),
    ("session_background_jobs_stop", {"target": "cloude_b", "targets": [{"pid": i + 1, "start": START} for i in range(21)]}),
])
def test_a_bad_write_is_refused_before_the_owner_is_asked(world, name, args):
    assert _call(name, args)["isError"] is True
    assert world == [] and pending.get_store().list() == []


def test_external_stop_stays_pending_under_beast_until_the_owner_approves(world, monkeypatch):
    arm_beast(monkeypatch, lambda: True)
    assert _body(_call("session_external_stop", {"session_name": "outside_tmux"}))["status"] == "pending"
    assert world == [] and asyncio.run(beast_mode.approve_pending()) == 0 and world == []
    _approve_all()
    assert [c[0].split(":")[1] for c in world] == ["destroy_external_session"]
    assert world[0][1][1] == "outside_tmux" and world[0][2] == {"confirm_name": None}


def test_a_swarm_leader_is_refused_because_the_tool_cannot_send_confirm_name(world, monkeypatch):
    from fastapi import HTTPException

    from src.core.swarm import body, leaders

    async def run_db(fn):
        return fn(None)

    async def route(request, name, confirm_name=None):
        seen.append(confirm_name)
        await leaders.require_confirm(tmux_name=name, confirm_name=confirm_name)

    seen: list = []
    leader = {"id": 1, "rank": "alpha", "display_name": "Acme HQ"}
    monkeypatch.setattr(body, "run_db", run_db)
    monkeypatch.setattr(leaders, "leader_row", lambda conn, uuid, name: leader if name == "leader_body" else None)
    monkeypatch.setattr("src.api.session_attach_routes.destroy_external_session", route)
    assert "confirm_name" not in tools._TOOLS["session_external_stop"][1]
    assert _call("session_external_stop", {"session_name": "leader_body", "confirm_name": "Acme HQ"})["isError"] is True
    _call("session_external_stop", {"session_name": "leader_body"})
    _approve_all()
    assert seen == [None]
    with pytest.raises(HTTPException) as err:
        asyncio.run(route(None, "leader_body", seen[0]))
    assert err.value.status_code == 409 and err.value.detail["code"] == "leader_protected"
    asyncio.run(route(None, "plain_body", None))


def test_plain_act_writes_wait_without_beast_and_run_at_once_with_it(world, monkeypatch):
    calls = {
        "session_recreate": {"target": ASLEEP, "agent_type": "claude"},
        "session_imported_restart": {"session_uuid": UUID, "agent_type": "claude"},
        "session_background_job_stop": {"target": "cloude_b", "pid": 4242, "start": START},
        "session_background_jobs_stop": {"target": "cloude_b", "targets": [{"pid": 4242, "start": START}]},
    }
    for name, args in calls.items():
        assert _body(_call(name, args))["status"] == "pending", name
    assert world == []
    _approve_all()
    by_route = {c[0].split(":")[1]: c for c in world}
    assert set(by_route) == {"recreate_session", "imported_restart", "terminate_background_process", "terminate_background_processes"}
    recreate = by_route["recreate_session"][1][1]
    assert (recreate.session_uuid, recreate.agent_type, recreate.account_id) == (ASLEEP, "claude", None)
    imported = by_route["imported_restart"][1][1]
    assert (imported.session_uuid, imported.agent_type) == (UUID, "claude")
    one = by_route["terminate_background_process"][1]
    assert (one[1], one[2], one[3].start) == ("ses_cloude_b", 4242, START)
    many = by_route["terminate_background_processes"][1]
    assert many[1] == "ses_cloude_b" and [(t.pid, t.start) for t in many[2].targets] == [(4242, START)]
    world.clear()
    arm_beast(monkeypatch, lambda: True)
    for name, args in calls.items():
        assert _body(_call(name, args)).get("status") != "pending", name
    assert len(world) == 4


def test_an_external_token_waits_and_a_read_token_is_refused(world):
    held = _call("session_background_job_stop", {"target": "cloude_b", "pid": 9, "start": START}, EXTERNAL)
    assert _body(held)["status"] == "pending" and world == []
    assert _call("session_background_job_stop", {"target": "cloude_b", "pid": 9, "start": START}, READ_ONLY)["isError"] is True


def test_recreate_needs_a_wrapper_from_the_caller_or_the_row(world):
    _call("session_recreate", {"target": ASLEEP})
    _approve_all()
    assert world == []


def test_adopt_and_unarchive_reach_their_routes_with_a_body(world):
    held = _call("session_adopt", {"session_name": "outside_tmux"})
    assert _body(held)["status"] == "pending" and world == []
    _approve_all()
    assert world[0][0].endswith("adopt_session") and world[0][1][1].session_name == "outside_tmux"
    _call("session_record_unarchive", {"session_uuid": UUID})
    assert world[1][0].endswith("unarchive_session_record") and world[1][1][1] == UUID


def test_background_set_builds_the_request_and_clears_on_nothing(world):
    _call("session_background_set", {"target": "cloude_b", "theme_id": "matrix", "dim": 0.5, "disabled": False})
    _call("session_background_set", {"target": "cloude_b"})
    first, second = (c[1][2] for c in world)
    assert world[0][1][1] == "cloude_b"
    assert (first.theme_id, first.dim, first.disabled) == ("matrix", 0.5, False)
    assert (second.theme_id, second.dim, second.disabled) == (None, None, False)


def test_the_slice_two_ledger_rows_moved_as_the_ratchet_expects():
    assert "deferred:2" not in LEDGER.values()
    gone = ["DELETE /api/v1/sessions/external/{name}", "GET /api/v1/session-backgrounds", "GET /api/v1/session-tasks",
            "GET /api/v1/sessions/imported/restart/preview", "GET /api/v1/sessions/records",
            "GET /api/v1/sessions/recreate/preview", "GET /api/v1/sessions/restart/preview",
            "PATCH /api/v1/sessions/{session_name}/background", "POST /api/v1/sessions/adopt",
            "POST /api/v1/sessions/imported/restart", "POST /api/v1/sessions/records/{session_uuid}/unarchive",
            "POST /api/v1/sessions/recreate", "POST /api/v1/sessions/{session_id}/background-work/terminate-all",
            "POST /api/v1/sessions/{session_id}/background-work/{pid}/terminate"]
    assert not [k for k in gone if k in LEDGER]
    assert LEDGER["GET /api/v1/sessions/logs"] == "out:superseded"
    assert {k: LEDGER[k] for k in ("GET /api/v1/sessions/companions", "GET /api/v1/sessions/{session_uuid}/restart/accounts",
                                   "POST /api/v1/sessions/{session_id}/fork-to", "POST /api/v1/sessions/{session_name}/fork")} == {
        "GET /api/v1/sessions/companions": "out:owner-only",
        "GET /api/v1/sessions/{session_uuid}/restart/accounts": "out:owner-only",
        "POST /api/v1/sessions/{session_id}/fork-to": "out:forks-session",
        "POST /api/v1/sessions/{session_name}/fork": "out:forks-session"}
