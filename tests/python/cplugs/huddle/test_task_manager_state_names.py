
from __future__ import annotations

import pytest

from src.core.mcp import tools
from src.cplugs.huddle import inbox_filing, rules, state_request, state_rungs
from tests.python.cplugs.huddle.test_task_manager_focus import CALLER, add, call, client, setup  # noqa: F401

BASE = "/api/v1/cplugs/huddle"
PAIRS = list(state_rungs.RENAMES)
IDS = [f"{old}-to-{new}" for old, new in PAIRS]
CLAUDE_PAIRS = [(old, new) for old, new in PAIRS if new in rules.CLAUDE_STATES]


def state_of(client, item: int) -> str:
    return next(i for i in client.get(f"{BASE}/lists/all").json()["items"] if i["id"] == item)["state"]


def test_the_alias_table_and_the_reader_are_gone():
    assert not any(hasattr(rules, name) for name in ("STATE_ALIASES", "canonical_state", "canonical_state_args", "STATE_ARGS"))


@pytest.mark.parametrize("old,new", PAIRS, ids=IDS)
def test_the_owner_route_refuses_a_retired_name_and_leaves_the_item(client, old, new):
    item = add(client, "all", "x")
    before = state_of(client, item)
    answer = client.patch(f"{BASE}/items/{item}", json={"state": old})
    assert 400 <= answer.status_code < 500
    assert state_of(client, item) == before


@pytest.mark.parametrize("old,new", PAIRS, ids=IDS)
def test_an_agent_is_refused_a_retired_name_through_update_and_batch(client, setup, old, new):
    ok, made = call(setup.manager, "task_manager_add", {"list": "all", "text": "mine"})
    ok, refused = call(setup.manager, "task_manager_update", {"item": made["id"], "state": old})
    assert not ok
    ok, batch = call(setup.manager, "task_manager_batch_run", {"list_id": "all", "ops": [{"op": "update", "item_id": made["id"], "state": old}]})
    assert not ok or batch["results"][0].get("state") != new
    assert state_of(client, made["id"]) == "open"


@pytest.mark.parametrize("old,new", PAIRS, ids=IDS)
def test_fork_refuses_a_retired_name_on_the_route(client, old, new):
    item = add(client, "all", "x")
    assert 400 <= client.post(f"{BASE}/items/{item}/fork", json={"fork_state": old}).status_code < 500


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


@pytest.mark.parametrize("old,new", PAIRS, ids=IDS)
def test_the_add_box_filing_refuses_a_retired_name(old, new):
    with pytest.raises(rules.TaskManagerInvalid):
        inbox_filing.parse_specs([{"title": "t", "text": "x", "state": old}])


@pytest.mark.parametrize("old,new", PAIRS, ids=IDS)
def test_a_stored_approval_card_still_reads_its_old_state_names(old, new):
    assert state_request.canonical_shown({"from_state": old, "to_state": old, "reason": old, "item": 3}) == {"from_state": new, "to_state": new, "reason": old, "item": 3}
