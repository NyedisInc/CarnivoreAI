
from __future__ import annotations

import asyncio
import json

from src.core.mcp import pending, tools
from src.core.mcp.caller import AgentCaller
from src.core.project_pack import jobs
from tests.python.project_pack.pack_world import storage_row

PANE = AgentCaller("ses_a", "cloude_a", "ses_a")


class View:

    gate_waited = False


def _call(name: str, args: dict) -> dict:
    return asyncio.run(tools.call_tool(View(), PANE, name, args))


def _text(answer: dict) -> dict:
    return json.loads(answer["content"][0]["text"])


def test_pack_and_unpack_wait_for_approval_with_the_plan_and_the_warning_on_the_card(world, monkeypatch):
    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    monkeypatch.setattr(pending, "MAX_WAIT_SECONDS", 0.05)
    pid = world.ids["oldsite"]
    plan = _text(_call("project_pack", {"project": pid}))
    assert plan["ok"] is True and plan["fingerprint"]
    refused = _call("project_pack", {"project": pid, "apply": True})
    assert refused["isError"] and "plan_fingerprint" in refused["content"][0]["text"]
    assert "pending" in str(_call("project_pack", {"project": pid, "apply": True, "plan_fingerprint": plan["fingerprint"]}))
    store = pending.get_store()
    assert storage_row(world) == {}
    card = store.list()[0]
    assert "pack project" in card["args_summary"] and card["display"]["verb"] == "pack"
    asyncio.run(store.approve(card["id"]))
    jobs.join(pid)
    assert storage_row(world)["state"] == "packed"
    archive = world.root / storage_row(world)["archive_name"]
    with open(archive, "ab") as handle:
        handle.write(b"x")
    plan = _text(_call("project_unpack", {"project": pid}))
    assert plan["integrity"]["status"] == "modified"
    assert "pending" in str(_call("project_unpack", {"project": pid, "apply": True, "plan_fingerprint": plan["fingerprint"]}))
    card = pending.get_store().list()[0]
    assert "WARNING" in card["args_summary"] and card["display"]["tone"] == "danger"
    assert card["display"]["consequences"][-1]["key"] == "archive_modified"
