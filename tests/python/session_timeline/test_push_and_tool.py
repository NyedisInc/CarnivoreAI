
from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from types import SimpleNamespace

from src.core.lineage import graph, milestones
from src.core.mcp import bookmark_tools, tools
from src.core.mcp.caller import AgentCaller
from src.core.resource_push import topics
from src.core.session_timeline import gather
from src.cplugs.save.vault import points as vault_points, retention
from src.cplugs.save.vault.identity import Identity
from tests.python.session_timeline.conftest import NOW, OLD
from tests.python.time_machine import helpers as tm_helpers

TOPIC = topics.SESSION_TIMELINE


def test_the_topic_is_advertised_so_a_client_stops_polling_for_it():
    assert TOPIC in topics.RESOURCE_TOPICS and TOPIC in topics.all_topics()


def test_a_new_edge_names_the_topic_and_a_repeat_does_not(env, pushed):
    with closing(sqlite3.connect(env["db"])) as conn:
        assert graph.add_edge(conn, "conversation", "a", "conversation", "b", "clear") == "added"
        assert pushed == [TOPIC]
        assert graph.add_edge(conn, "conversation", "a", "conversation", "b", "clear") == "present"
        assert pushed == [TOPIC]


def test_a_new_milestone_names_the_topic_and_a_duplicate_does_not(env, pushed):
    with closing(sqlite3.connect(env["db"])) as conn:
        assert milestones.add_milestone(conn, "c", "compact", "jsonl_scan", at_ts="2026-10-10T09:00:00Z", jsonl_line=5)
        assert pushed == [TOPIC]
        assert not milestones.add_milestone(conn, "c", "compact", "jsonl_scan", at_ts="2026-10-10T09:00:00Z", jsonl_line=5)
        assert pushed == [TOPIC]


def test_restore_point_writes_pins_deletes_and_sweeps_each_name_the_topic(env, pushed):
    vault, plan = env["vault"], env["plan"]
    plan.files[0].path.write_bytes(plan.files[0].path.read_bytes() + b'{"type":"user"}\n')
    first = vault.manifests.point_ids(OLD)[-1]
    vault.manifests.set_pinned(OLD, first, True)
    out = vault.capture(plan, Identity(), "remove", now=datetime(2026, 10, 10, 11, 0, 5, tzinfo=timezone.utc))
    vault.manifests.set_pinned(OLD, first, False)
    del pushed[:-1]
    assert pushed == [TOPIC] and out.status == "written"
    del pushed[:]
    vault_points.set_pinned(vault, OLD, out.point_id, True)
    vault_points.set_pinned(vault, OLD, out.point_id, False)
    assert pushed == [TOPIC, TOPIC]
    del pushed[:]
    vault_points.delete_point(vault, OLD, out.point_id)
    assert pushed == [TOPIC]
    del pushed[:]
    held = []
    for i in range(12):
        newest = vault.manifests.point_ids(OLD)[-1]
        if not vault.manifests.is_pinned(OLD, newest):
            held.append(newest)
            vault.manifests.set_pinned(OLD, newest, True)
        plan.files[0].path.write_bytes(plan.files[0].path.read_bytes() + b'{"type":"user","n":%d}\n' % i)
        vault.capture(plan, Identity(), "follow", now=datetime(2026, 10, 10, 12, 0, i, tzinfo=timezone.utc))
    for point_id in held:
        vault.manifests.set_pinned(OLD, point_id, False)
    del pushed[:]
    assert retention.thin_unit(vault, OLD) and pushed.count(TOPIC) >= 1
    assert len(vault_points.list_points(vault, OLD)) == 1


def _call(args):
    info = SimpleNamespace(session=SimpleNamespace(id="ses_1"), tmux_session="cloude_fixture", session_row_id=7, host_key="local")

    class View:
        app = None

        async def list_session_infos(self):
            return [info]

    caller = AgentCaller("ses_1", "cloude_fixture", "ses_1")
    return asyncio.run(tools.call_tool(View(), caller, "session_timeline_get", args))


def test_the_tool_returns_the_route_answer(env, monkeypatch):
    monkeypatch.setattr(gather, "_db_path", lambda: env["db"])
    monkeypatch.setattr(bookmark_tools, "_session_uuid_of_row", lambda row_id: "row-uuid-1")
    result = _call({"target": "ses_1"})
    assert not result.get("isError"), result
    body = json.loads(result["content"][0]["text"])
    assert body["session_uuid"] == "row-uuid-1" and body["truncated"] is False
    assert [b["conversation_id"] for b in body["bars"]][0] == OLD
    assert {m["kind"] for m in body["marks"]} == {"restart", "restore", "bookmark", "compact"}


def test_the_tool_is_a_read_with_a_short_description():
    assert "session_timeline_get" not in tools.WRITE_TOOLS
    [definition] = [d for d in tools.tool_definitions(None) if d["name"] == "session_timeline_get"]
    assert len(definition["description"]) <= 120
