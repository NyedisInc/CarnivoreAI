
from __future__ import annotations

import json

from src.core.mcp import tools
from tests.python.cplugs.huddle.test_task_manager_mcp import call, huddle_store, manager  # noqa: F401

MAX_DEFINITION_BYTES = 5000


def definition_bytes(definition: dict) -> int:
    return len(json.dumps(definition, separators=(",", ":")).encode("utf-8"))


def test_every_huddle_tool_definition_is_under_5000_bytes():
    sizes = {d["name"]: definition_bytes(d) for d in tools.tool_definitions(None) if d["name"].startswith("huddle_")}
    assert len(sizes) >= 20
    assert {name: size for name, size in sizes.items() if size >= MAX_DEFINITION_BYTES} == {}


def test_the_batch_schema_keeps_its_common_fields_and_leaves_the_rare_ones_to_the_op_s_own_tool():
    batch = next(d for d in tools.tool_definitions(None) if d["name"] == "task_manager_batch_run")
    op = batch["inputSchema"]["properties"]["ops"]["items"]
    assert {"op", "item_id", "text", "state", "kind", "phase", "note", "group", "list", "expected_revision"} <= set(op["properties"])
    assert not {"review_description", "marker", "fire_at", "repeat", "github_issue"} & set(op["properties"])
    assert op["additionalProperties"] is True
    assert "same fields as its own tool" in batch["description"]


def test_batch_ops_with_rare_fields_still_work_and_are_still_checked(manager):
    store = huddle_store(manager)
    ok, out = call(manager, "task_manager_batch_run", {"list_id": "all", "ops": [
        {"op": "add", "text": "from a batch", "title": "Batch title", "list": "all", "perceived_ask": "file it", "github_issue": "https://github.com/NyedisInc/CarnivoreAI/issues/1757"},
        {"op": "add", "text": "second", "list": "all", "fire_at": "2099-01-01T09:00:00-04:00"},
    ]}, raw=True)
    assert ok and out["applied"] == 2, out
    first, second = (r["item_id"] for r in out["results"])
    ok, out = call(manager, "task_manager_batch_run", {"list_id": "all", "ops": [
        {"op": "update", "item_id": first, "state": "review", "review_summary": "done", "review_description": "what changed", "review_action": "read", "marker": "hexagon"},
        {"op": "update", "item_id": second, "repeat": {"freq": "daily", "time": "09:00"}},
        {"op": "update", "item_id": second, "no_such_field": 1},
    ]}, raw=True)
    assert ok and [r["ok"] for r in out["results"]] == [True, True, False], out
    assert "unknown argument" in out["results"][2]["error"]
    item = store.item(first)
    assert item["state"] == "review" and item["review_summary"] == "done" and item["marker"] == "hexagon" and item["title"] == "Batch title"
    assert store.item(second)["start_trigger"]["repeat"]
