
import json
import subprocess
from unittest import mock

import pytest

from src.core.background_agents import (
    KIND_BACKGROUND,
    QUERY_OK,
    QUERY_UNAVAILABLE,
    QUERY_UNPARSEABLE,
    AgentsResult,
    list_background_agents,
)

FORK_AGENT = {
    "pid": 4762,
    "id": "deb83b29",
    "cwd": "/x/Labbench",
    "kind": "background",
    "startedAt": 1787933593112,
    "sessionId": "deb83b29-170b-4b8a-89de-9d3281309fba",
    "name": "Base",
    "status": "idle",
    "state": "done",
}
INTERACTIVE_AGENT = {
    "pid": 1,
    "cwd": "/x",
    "kind": "interactive",
    "startedAt": 1,
    "sessionId": "aaaa-bbbb",
    "name": "a tmux session",
    "status": "idle",
}


def _run(stdout="[]", returncode=0):
    return mock.patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=""
        ),
    )


def test_a_background_agent_is_found_and_parsed():
    with _run(json.dumps([FORK_AGENT])):
        r = list_background_agents(claude_path="/fake/claude")
    assert r.measured is True
    assert len(r.agents) == 1
    a = r.agents[0]
    assert a.short_id == "deb83b29"
    assert a.name == "Base"
    assert a.state == "done"
    assert a.pid == 4762


def test_interactive_sessions_are_excluded():
    with _run(json.dumps([INTERACTIVE_AGENT, FORK_AGENT])):
        r = list_background_agents(claude_path="/fake/claude")
    assert [a.short_id for a in r.agents] == ["deb83b29"]


def test_a_genuinely_empty_list_is_measured():
    with _run("[]"):
        r = list_background_agents(claude_path="/fake/claude")
    assert r.agents == []
    assert r.measured is True, "no agents is a real answer"



def test_a_timeout_is_not_an_empty_list():
    with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("x", 10)):
        r = list_background_agents(claude_path="/fake/claude")
    assert r.agents == []
    assert r.measured is False
    assert r.status == QUERY_UNAVAILABLE
    assert "did not answer" in (r.detail or "")


def test_a_missing_binary_is_not_an_empty_list():
    r = list_background_agents(claude_path="/no/such/claude")
    assert r.measured is False
    assert r.status == QUERY_UNAVAILABLE


def test_a_nonzero_exit_is_not_an_empty_list():
    with _run("[]", returncode=2):
        r = list_background_agents(claude_path="/fake/claude")
    assert r.measured is False
    assert "exited 2" in (r.detail or "")


def test_unparseable_output_is_its_own_state():
    with _run("not json at all"):
        r = list_background_agents(claude_path="/fake/claude")
    assert r.status == QUERY_UNPARSEABLE
    assert r.measured is False


def test_a_json_object_instead_of_an_array_is_unparseable():
    with _run('{"agents": []}'):
        r = list_background_agents(claude_path="/fake/claude")
    assert r.status == QUERY_UNPARSEABLE



def test_a_record_gaining_or_losing_fields_does_not_break_the_listing():
    odd = {"kind": KIND_BACKGROUND, "sessionId": "s1", "brand_new_field": 1}
    with _run(json.dumps([odd])):
        r = list_background_agents(claude_path="/fake/claude")
    assert r.measured is True
    assert r.agents[0].session_id == "s1"
    assert r.agents[0].name is None


def test_a_record_with_no_session_id_is_dropped_not_faked():
    with _run(json.dumps([{"kind": KIND_BACKGROUND, "name": "nameless"}])):
        r = list_background_agents(claude_path="/fake/claude")
    assert r.agents == []
    assert r.measured is True


def test_measured_is_the_flag_callers_must_branch_on():
    assert AgentsResult(status=QUERY_OK).measured is True
    assert AgentsResult(status=QUERY_UNAVAILABLE).measured is False
    assert AgentsResult(status=QUERY_UNPARSEABLE).measured is False
