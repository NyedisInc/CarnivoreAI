
from __future__ import annotations

import itertools
from types import SimpleNamespace

import pytest

from src.core.approvals import beast_grid
from src.core.approvals.auto_answer.engine import grid_policy
from src.core.beast_prompts.wiring import prompt_allowed
from src.core.mcp import beast_mode
from src.cplugs.host.mcp import INBOX_TOOLS
from tests.python.beast_mode.grid import install

COMBOS = list(itertools.product((False, True), repeat=2))
IDS = ["neither", "on_only", "off_only", "both"]
CLAUDE_PROMPT = SimpleNamespace(family="claude")


def _grid(monkeypatch, row: str, off: bool, on: bool, armed: bool, prompts: bool) -> None:
    values = {f"{row}Off": off, f"{row}On": on}
    install(monkeypatch, values, armed=lambda: armed, prompts=lambda: prompts)


@pytest.mark.parametrize("off,on", COMBOS, ids=IDS)
@pytest.mark.parametrize("armed", [False, True], ids=["disarmed", "armed"])
def test_agent_writes_follow_the_box_of_the_current_mode(monkeypatch, off, on, armed):
    _grid(monkeypatch, "agentWrites", off, on, armed, prompts=False)
    expected = on if armed else off
    assert beast_mode.approval_skip("session_wake") is expected
    assert beast_mode.writes_handled() is expected


@pytest.mark.parametrize("off,on", COMBOS, ids=IDS)
@pytest.mark.parametrize("armed,prompts", [(False, False), (True, False), (True, True)], ids=["disarmed", "armed_no_prompts", "armed_prompts"])
def test_a_prompt_row_follows_the_box_of_its_mode_and_beast_on_needs_the_prompts_scope(monkeypatch, off, on, armed, prompts):
    _grid(monkeypatch, "claudePermission", off, on, armed, prompts)
    expected = on if (armed and prompts) else off
    assert prompt_allowed(CLAUDE_PROMPT) is expected


@pytest.mark.parametrize("off,on", COMBOS, ids=IDS)
@pytest.mark.parametrize("armed", [False, True], ids=["disarmed", "armed"])
def test_a_startup_row_follows_the_box_of_the_current_mode(monkeypatch, off, on, armed):
    _grid(monkeypatch, "folderTrust", off, on, armed, prompts=False)
    assert grid_policy().rule_on(beast_grid.ROW_FOLDER_TRUST) is (on if armed else off)


def test_the_defaults_through_the_gates(monkeypatch):
    for armed in (False, True):
        install(monkeypatch, {}, armed=lambda armed=armed: armed, prompts=lambda armed=armed: armed)
        policy = grid_policy()
        assert all(policy.rule_on(r) for r in ("dev_channels", "folder_trust", "external_imports", "chrome_decline"))
        assert beast_mode.writes_handled() is armed and prompt_allowed(CLAUDE_PROMPT) is armed
        assert prompt_allowed(SimpleNamespace(family="codex")) is armed


def test_hard_rules_are_never_skipped_whatever_is_ticked(monkeypatch):
    every = {key: True for key in beast_grid.cell_defaults()}
    for armed in (False, True):
        install(monkeypatch, every, armed=lambda armed=armed: armed, prompts=lambda armed=armed: armed)
        for action in beast_mode.ALWAYS_WAITS | beast_mode.RETAINED_APPROVALS:
            assert beast_mode.approval_skip(action) is False, action
        assert beast_mode.approval_skip("session_dialog_answer", own_dialog=True) is False
        assert beast_mode.approval_skip("session_dialog_answer") is True
        assert INBOX_TOOLS, "a shipped plugin declares an inbox-gated tool (the case this guards)"
        for tool in INBOX_TOOLS:
            assert beast_mode.approval_skip(tool) is False, tool


def test_no_locked_row_and_no_unknown_row_is_ever_handled(monkeypatch):
    every = {key: True for key in beast_grid.cell_defaults()}
    policy = install(monkeypatch, every, armed=lambda: True, prompts=lambda: True)
    for row in (*beast_grid.LOCKED_ROWS, "bypass_permissions", ""):
        assert policy.handles(row) is False, row
    assert beast_grid.ROW_AGENT_WRITES not in beast_grid.LOCKED_ROWS
    assert not set(beast_grid.LOCKED_ROWS) & {row.id for row in beast_grid.ROWS}


@pytest.mark.parametrize("bad", ["yes", 1, None, "true", [True]])
def test_a_malformed_box_reads_unticked_never_wider(monkeypatch, bad):
    install(monkeypatch, {"agentWritesOn": bad, "folderTrustOff": bad}, armed=lambda: True, prompts=lambda: False)
    assert beast_mode.writes_handled() is False
    install(monkeypatch, {"folderTrustOff": bad}, armed=lambda: False, prompts=lambda: False)
    assert grid_policy().rule_on("folder_trust") is False


def test_the_arm_dialog_count_follows_the_agent_writes_beast_on_box(monkeypatch):
    from src.core.mcp import pending

    store = pending.PendingActions()
    monkeypatch.setattr(pending, "_store", store)
    store.create(caller_session_id="ses_a", caller_tmux="a", target_session_id="ses_b", target_tmux="b", action="session_wake",
                 args_summary="wake b", execute=None, args={})
    install(monkeypatch, {"agentWritesOn": False}, armed=lambda: False, prompts=lambda: False)
    assert len(store.beast_candidates()) == 1 and beast_mode.pending_count() == 0
    install(monkeypatch, {"agentWritesOn": True}, armed=lambda: False, prompts=lambda: False)
    assert beast_mode.pending_count() == 1


def test_the_quiet_bolt_rows_are_the_beast_off_auto_approve_boxes(monkeypatch):
    install(monkeypatch, {}, armed=lambda: False, prompts=lambda: False)
    assert beast_mode.off_column_rows() == [], "the defaults auto-approve nothing with beast off"
    install(monkeypatch, {"agentWritesOff": True, "codexApprovalOff": True, "folderTrustOff": True}, armed=lambda: True,
            prompts=lambda: True)
    assert beast_mode.off_column_rows() == ["codex_approval", "agent_writes"], "whatever the mode, startup rows never count"


def test_the_status_reports_each_row_both_boxes_the_mode_and_what_is_handled_now(monkeypatch):
    policy = install(monkeypatch, {"agentWritesOff": True}, armed=lambda: False, prompts=lambda: False)
    rows = {r["id"]: r for r in policy.status()["rows"]}
    assert rows["agent_writes"] == {"id": "agent_writes", "kind": "writes", "off": True, "on": True, "mode": "off", "handled_now": True,
                                    "cells": {"off": "agentWritesOff", "on": "agentWritesOn"}}
    assert rows["folder_trust"]["risk"] == "medium" and rows["claude_permission"]["handled_now"] is False
    assert policy.status()["always_asks"] == list(beast_grid.LOCKED_ROWS)
    assert policy.status()["unconfirmed_rows"] == list(beast_grid.UNCONFIRMED_ROWS)


def test_the_owner_status_names_the_beast_off_auto_approve_rows_even_disarmed(monkeypatch):
    import asyncio

    from src.api import beast_mode_routes
    from src.config import settings

    switch = SimpleNamespace(beast_mode=False, beast_prompts=False, beast_mode_until=None, beast_mode_since=None)
    monkeypatch.setattr(type(settings), "load_auth_config", lambda self: SimpleNamespace(mcp=switch))
    install(monkeypatch, {"claudePermissionOff": True})
    status = asyncio.run(beast_mode_routes.get_beast_mode())
    assert status["enabled"] is False and status["auto_off_rows"] == ["claude_permission"]


def test_the_live_policy_reads_the_grid_stored_in_config_json(monkeypatch):
    from src.config import settings
    from src.core.approvals import beast_policy

    mcp = SimpleNamespace(beast_mode=True, beast_prompts=True, beast_mode_until=None, beast_mode_since=None,
                          beast_grid={"agentWritesOn": False, "folderTrustOff": False, "claudePermissionOff": "yes"}, beast_trust_scope="every")
    monkeypatch.setattr(type(settings), "load_auth_config", lambda self: SimpleNamespace(mcp=mcp))
    policy = beast_policy.current()
    assert policy.handles("agent_writes") is False, "armed, the beast on box is unticked"
    assert policy.handles("claude_permission") is True and policy.ticked_in("claude_permission", "off") is False, "a non-bool box reads unticked"
    assert policy.ticked_in("folder_trust", "off") is False and policy.ticked_in("folder_trust", "on") is True
    assert policy.trust_scope() == "every"
    mcp.beast_trust_scope = "elsewhere"
    assert policy.trust_scope() == "projects", "an unknown scope reads as the narrow default"
    mcp.beast_mode = False
    assert policy.handles("claude_permission") is False and policy.handles("folder_trust") is False


def test_an_unreadable_config_handles_no_beast_on_row_and_reads_defaults_for_the_rest(monkeypatch):
    from src.config import settings
    from src.core.approvals import beast_policy

    def unreadable(self):
        raise OSError("config.json")

    monkeypatch.setattr(type(settings), "load_auth_config", unreadable)
    assert beast_mode.stored_armed() is False and beast_mode.beast_enabled() is False
    policy = beast_policy.current()
    assert policy.handles("agent_writes") is False and policy.handles("claude_permission") is False
