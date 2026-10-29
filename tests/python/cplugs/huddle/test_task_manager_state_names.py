
from __future__ import annotations

import pytest

from src.core.mcp import tools
from src.cplugs.huddle import inbox_filing, rules, state_rungs
from tests.python.cplugs.huddle.test_task_manager_focus import CALLER, add, call, client, setup  # noqa: F401

BASE = "/api/v1/cplugs/huddle"
PAIRS = list(state_rungs.RENAMES)
IDS = [f"{old}-to-{new}" for old, new in PAIRS]
CLAUDE_PAIRS = [(old, new) for old, new in PAIRS if new in rules.CLAUDE_STATES]


def state_of(client, item: int) -> str:
    return next(i for i in client.get(f"{BASE}/lists/all").json()["items"] if i["id"] == item)["state"]


def test_canonical_state_reads_a_retired_name_as_its_replacement_and_leaves_everything_else():
    for old, new in PAIRS:
        assert rules.canonical_state(old) == new and rules.canonical_state(new) == new
    assert rules.canonical_state(None) is None and rules.canonical_state(7) == 7 and rules.canonical_state(["x"]) == ["x"]
    out = rules.canonical_state_args({"state": PAIRS[0][0], "fork_state": PAIRS[0][0], "text": PAIRS[0][0], "item": 3})
    assert out == {"state": PAIRS[0][1], "fork_state": PAIRS[0][1], "text": PAIRS[0][0], "item": 3}


@pytest.mark.parametrize("old,new", PAIRS, ids=IDS)
def test_the_owner_route_accepts_a_retired_name_and_answers_the_current_one(client, old, new):
    item = add(client, "all", "x")
    answer = client.patch(f"{BASE}/items/{item}", json={"state": old})
    assert answer.status_code == 200 and answer.json()["state"] == new
    assert state_of(client, item) == new


@pytest.mark.parametrize("old,new", CLAUDE_PAIRS, ids=[f"{o}-to-{n}" for o, n in CLAUDE_PAIRS])
def test_an_agent_sets_a_retired_name_through_update_and_batch(client, setup, old, new):
    ok, made = call(setup.manager, "task_manager_add", {"list": "all", "text": "mine"})
    park = {"waiting_on": "the staging restart", "wait_kind": "install"} if new == "waiting" else {}
    ok, answer = call(setup.manager, "task_manager_update", {"item": made["id"], "state": old, **park})
    assert ok and answer["state"] == new
    ok, again = call(setup.manager, "task_manager_add", {"list": "all", "text": "mine too"})
    ok, batch = call(setup.manager, "task_manager_batch_run", {"list_id": "all", "ops": [{"op": "update", "item_id": again["id"], "state": old, **park}]})
    assert ok and batch["results"][0]["state"] == new


@pytest.mark.parametrize("old,new", [p for p in PAIRS if p not in CLAUDE_PAIRS], ids=lambda p: str(p))
def test_an_agent_still_cannot_tick_by_a_retired_name(client, setup, old, new):
    ok, made = call(setup.manager, "task_manager_add", {"list": "all", "text": "mine"})
    ok, refused = call(setup.manager, "task_manager_update", {"item": made["id"], "state": old})
    assert not ok and "approves" in refused


@pytest.mark.parametrize("old,new", PAIRS, ids=IDS)
def test_fork_takes_a_retired_name_on_the_route(client, old, new):
    item = add(client, "all", "x")
    made = client.post(f"{BASE}/items/{item}/fork", json={"fork_state": old})
    assert made.status_code == 200 and made.json()["fork"]["state"] == new


def test_the_tool_schemas_advertise_only_the_current_names():
    retired = {old for old, _new in PAIRS}
    listed = {d["name"]: d["inputSchema"]["properties"] for d in tools.tool_definitions()}
    update = listed["task_manager_update"]["state"]["enum"]
    assert update[:2] == ["open", "working"] and set(rules.CLAUDE_STATES) <= set(update)
    assert not retired & set(update)
    assert not retired & set(listed["task_manager_add"]["state"]["enum"])
    for field in ("fork_state", "parent_state"):
        assert not retired & set(listed["task_manager_fork"][field]["enum"]), field
    filing = listed["task_manager_entry_import"]["items"]["items"]["properties"]["state"]["enum"]
    assert not retired & set(filing) and set(filing) == set(inbox_filing.STATES)
    assert not {old for old, new in PAIRS if new not in rules.CLAUDE_STATES} & set(update)


FILING_PAIRS = [(old, new) for old, new in PAIRS if new in inbox_filing.STATES]


@pytest.mark.parametrize("old,new", FILING_PAIRS, ids=[f"{o}-to-{n}" for o, n in FILING_PAIRS] or None)
def test_the_add_box_filing_takes_a_retired_name(old, new):
    assert [s.state for s in inbox_filing.parse_specs([{"title": "t", "text": "x", "state": old}])] == [new]
