
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from types import SimpleNamespace

import pytest

from src.api import lineage_routes
from src.config import settings
from src.core.crosstalk import store
from src.core.db import transaction
from src.core.db_models import CURRENT_SCHEMA_VERSION, SESSION_ORIGIN_ADOPTED
from src.core.flow_data import mcp_event_fields, mcp_events, spawn_links
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.core.session_identity import record_instance
from tests.s7_helpers import TEST_SOCKET, migrated_connection, session_row


@pytest.fixture()
def world(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    conn = migrated_connection(state)
    with transaction(conn):
        for name, epoch in (("cloude_parent", 1_800_000_001), ("cloude_child", 1_800_000_002)):
            record_instance(conn, socket=TEST_SOCKET, name=name, epoch=epoch, origin=SESSION_ORIGIN_ADOPTED, working_dir="/tmp/x")
    parent, child = session_row(conn, "cloude_parent"), session_row(conn, "cloude_child")
    conn.close()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state)
    monkeypatch.setattr(store, "_notify", lambda: None)
    return SimpleNamespace(state=state, parent=parent, child=child)


def test_schema_v90_adds_the_tables_and_columns(world):
    assert CURRENT_SCHEMA_VERSION >= 90
    conn = migrated_connection(world.state)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(crosstalk_messages)")}
    assert {"agent_sent", "spawn_task", "landed_session_id", "landed_at", "landed_header", "landed_anchor", "delivery_path"} <= cols
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"agent_spawn_links", "mcp_events"} <= tables
    assert "result_ids" in {r[1] for r in conn.execute("PRAGMA table_info(mcp_events)")}
    conn.close()


def test_spawn_records_the_parent_on_the_row_the_lineage_graph_and_the_link_table(world):
    p, c = world.parent, world.child
    assert spawn_links.record_spawn(child_id="ses_c", child_uuid=c["session_uuid"], parent_id="ses_p", parent_uuid=p["session_uuid"],
                                    parent_kind="session", task_message_id="m-1", parent_row_id=p["id"], child_row_id=c["id"])
    assert not spawn_links.record_spawn(child_id="ses_c", child_uuid=c["session_uuid"], parent_id="ses_other", parent_uuid=None,
                                        parent_kind="session", task_message_id="m-2")
    conn = migrated_connection(world.state)
    row = conn.execute("SELECT parent_session_id, fork_kind FROM sessions WHERE id = ?", (c["id"],)).fetchone()
    edge = conn.execute("SELECT parent_id, child_id FROM lineage_edges WHERE edge_kind = 'spawned_by'").fetchone()
    conn.close()
    assert (row[0], row[1]) == (p["id"], "spawn")
    assert (edge[0], edge[1]) == (p["session_uuid"], c["session_uuid"])
    assert spawn_links.parent_of(child_uuid=c["session_uuid"])["parent_id"] == "ses_p"
    assert [k["child_id"] for k in spawn_links.children_of(parent_uuid=p["session_uuid"])] == ["ses_c"]


def test_an_external_parent_is_kept_without_touching_session_rows(world):
    c = world.child
    spawn_links.record_spawn(child_id="ses_c", child_uuid=c["session_uuid"], parent_id="mcp-token:7", parent_uuid=None,
                             parent_kind="external", task_message_id="m-1")
    conn = migrated_connection(world.state)
    assert conn.execute("SELECT parent_session_id FROM sessions WHERE id = ?", (c["id"],)).fetchone()[0] is None
    conn.close()
    assert spawn_links.parent_of(child_id="ses_c")["parent_kind"] == "external"


def test_the_lineage_read_exposes_the_spawn_link_and_children(world):
    p, c = world.parent, world.child
    spawn_links.record_spawn(child_id="ses_c", child_uuid=c["session_uuid"], parent_id="ses_p", parent_uuid=p["session_uuid"],
                             parent_kind="session", task_message_id="m-1", parent_row_id=p["id"], child_row_id=c["id"])
    child_view = asyncio.run(lineage_routes.lineage_of("session", c["session_uuid"]))
    parent_view = asyncio.run(lineage_routes.lineage_of("session", p["session_uuid"]))
    assert child_view.spawn_link["parent_uuid"] == p["session_uuid"] and child_view.spawn_children == []
    assert [k["child_uuid"] for k in parent_view.spawn_children] == [c["session_uuid"]] and parent_view.spawn_link is None


def _pair():
    a = {"key": "ua", "id": "sa", "uuid": "ua", "epoch": 1, "name": "A", "provider": "claude", "model": "opus"}
    b = {"key": "ub", "id": "sb", "uuid": "ub", "epoch": 2, "name": "B", "provider": "claude", "model": "opus"}
    store.grant_contact(a["key"], b["key"], 1, 2)
    return a, b


def test_a_native_delivery_keeps_the_receipt_id_and_the_exact_header(world):
    a, b = _pair()
    sent = store.reserve(sender=a, receiver=b, text="do the thing")
    assert sent["agent_sent"] == 1 and not sent["spawn_task"] and sent["landed_at"] is None
    store.claim_for("ub")
    receipt, conversation = "a" * 32, "11111111-2222-3333-4444-555555555555"
    assert store.mark_native_pending(sent["id"], receipt, conversation_id=conversation)
    store.finish(sent["id"], "delivered")
    row = store.get(sent["id"])
    assert row["reason"] is None
    assert row["landed_anchor"] == f"native:{receipt}:{conversation}"
    assert row["landed_session_id"] == "sb" and row["delivery_path"] == "native" and row["landed_at"] == row["delivered_at"]
    assert row["landed_header"] == f"crosstalk from @A (claude / opus) thread {sent['thread']} msg {sent['id']}"
    assert "do the thing" not in row["landed_header"]


def test_a_pasted_delivery_lands_without_an_anchor_and_a_spawn_task_is_flagged(world):
    a, b = _pair()
    task = store.reserve(sender=a, receiver=b, text="first task", spawn_task=True)
    assert task["spawn_task"] == 1 and task["agent_sent"] == 1
    store.claim_for("ub")
    store.finish(task["id"], "delivered")
    row = store.get(task["id"])
    assert row["delivery_path"] == "paste" and row["landed_anchor"] is None and row["landed_session_id"] == "sb"


def test_a_failed_delivery_records_no_landing(world):
    a, b = _pair()
    sent = store.reserve(sender=a, receiver=b, text="x")
    store.claim_for("ub")
    store.finish(sent["id"], "failed", "receiver gone")
    assert store.get(sent["id"])["landed_at"] is None


def test_event_fields_keep_ids_only_never_values():
    ids = mcp_event_fields.target_ids({"target": "ses_1", "text": "sk-live-SECRET and more", "to": "has space", "items": [3, 4, True],
                                       "title": "SECRET", "list": "12"})
    assert json.loads(ids) == {"items": ["3", "4"], "list": ["12"], "target": ["ses_1"]}
    assert "SECRET" not in ids and mcp_event_fields.target_ids({"text": "x"}) is None and mcp_event_fields.target_ids("nope") is None
    answer = {"content": [{"type": "text", "text": json.dumps({"id": "m-1", "text": "SECRET body", "task_message": {"id": "m-2"}, "thread": "t-1"})}]}
    got = mcp_event_fields.result_ids(answer)
    assert json.loads(got) == {"id": ["m-1"], "task_message": ["m-2"], "thread": ["t-1"]} and "SECRET" not in got


def test_outcomes():
    ok = {"content": [{"text": "{}"}]}
    err = lambda t: {"isError": True, "content": [{"text": t}]}  # noqa: E731
    assert mcp_event_fields.outcome_of(ok) == "ok"
    assert mcp_event_fields.outcome_of(err("owner denied it")) == "denied"
    assert mcp_event_fields.outcome_of(err("boom")) == "error"
    assert mcp_event_fields.outcome_of(err("boom"), denied_by_gate=True) == "denied"


def test_the_event_log_writes_arrival_and_completion_off_the_call_and_prunes(world):
    caller = AgentCaller("ses_1", "cloude_a", "ses_1")
    handle = mcp_events.begin(caller, "crosstalk_send", {"to": "ses_2", "text": "SECRET"})
    mcp_events.finish(handle, {"content": [{"text": json.dumps({"id": "m-9", "thread": "t-9"})}]})
    assert mcp_events.flush(10)
    [event] = mcp_events.recent(tool="crosstalk_send")
    assert (event["caller_session_id"], event["caller_kind"], event["outcome"]) == ("ses_1", "pane", "ok")
    assert json.loads(event["target_ids"]) == {"to": ["ses_2"]} and json.loads(event["result_ids"])["id"] == ["m-9"]
    assert event["duration_ms"] >= 0 and "SECRET" not in json.dumps(event)
    conn = migrated_connection(world.state)
    conn.execute("INSERT INTO mcp_events (call_id, started_at, tool, caller_kind) VALUES ('old', ?, 'x', 'pane')",
                 (time.time() - (mcp_events.RETENTION_DAYS + 1) * 86400,))
    conn.commit()
    conn.close()
    assert mcp_events.prune() == 1
    assert [e["call_id"] for e in mcp_events.recent(limit=10)] == [event["call_id"]]


def test_the_dispatcher_logs_every_call_and_marks_a_gate_refusal_denied(world):
    reader = AgentCaller("ext", "ext", "ext", "tok", "read")
    result = asyncio.run(tools.call_tool(SimpleNamespace(), reader, "session_stop", {"target": "ses_1"}))
    assert result.get("isError")
    assert mcp_events.flush(10)
    [event] = mcp_events.recent(tool="session_stop")
    assert (event["outcome"], event["caller_kind"], event["caller_session_id"]) == ("denied", "external", None)
    assert json.loads(event["target_ids"]) == {"target": ["ses_1"]}


def test_a_broken_store_never_breaks_a_call(world, monkeypatch):
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: world.state / "missing")
    caller = AgentCaller("ses_1", "cloude_a", "ses_1")
    handle = mcp_events.begin(caller, "whoami", {})
    mcp_events.finish(handle, {"content": []})
    assert mcp_events.flush(10)
    spawn_links.record_quietly(child_id="c", child_uuid=None, parent_id="p", parent_uuid=None, parent_kind="session", task_message_id=None)


def test_the_events_route_reads_the_log(world):
    from src.api import mcp_event_routes

    caller = AgentCaller("ses_1", "cloude_a", "ses_1")
    mcp_events.finish(mcp_events.begin(caller, "whoami", {}), {"content": []})
    assert mcp_events.flush(10)
    answer = asyncio.run(mcp_event_routes.list_mcp_events(tool="whoami", session_id=None, since=0.0, limit=10))
    assert answer.retention_days == mcp_events.RETENTION_DAYS and [e["tool"] for e in answer.events] == ["whoami"]
