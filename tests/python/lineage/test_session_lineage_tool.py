
from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.api import lineage_routes
from src.core.db import transaction
from src.core.db_models import SESSION_ORIGIN_ADOPTED
from src.core.lineage import constants as K
from src.core.lineage import graph, milestones
from src.core.mcp import bookmark_tools, lineage_tools, tools
from src.core.mcp.caller import AgentCaller
from src.core.session_claude_correlate_bind import bind_correlated_uuid
from src.core.session_identity import record_instance
from tests.s7_helpers import TEST_SOCKET, migrated_connection, session_row


@pytest.fixture()
def world(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    conn = migrated_connection(state)
    with transaction(conn):
        record_instance(conn, socket=TEST_SOCKET, name="cloude_life", epoch=1_800_000_000, origin=SESSION_ORIGIN_ADOPTED,
                        working_dir="/tmp/life")
        bind_correlated_uuid(conn, socket=TEST_SOCKET, name="cloude_life", epoch=1_800_000_000, claude_uuid="conv-c")
        uuid = session_row(conn, "cloude_life")["session_uuid"]
        graph.add_edge(conn, "conversation", "conv-a", "session", uuid, "clear", created_at="2026-10-10T10:00:00Z")
        graph.add_edge(conn, "conversation", "conv-a", "conversation", "conv-b", "clear", created_at="2026-10-10T10:00:00Z")
        graph.add_edge(conn, "conversation", "conv-b", "session", uuid, "rewind", created_at="2026-10-10T11:00:00Z",
                       detail={K.DETAIL_SPLIT_SESSION: "conv-b", K.DETAIL_SPLIT_MESSAGE: "m7", K.DETAIL_VIA: "bookmark_rewind"})
        graph.add_edge(conn, "conversation", "conv-b", "conversation", "conv-c", "rewind", created_at="2026-10-10T11:00:00Z",
                       detail={K.DETAIL_SPLIT_SESSION: "conv-b", K.DETAIL_SPLIT_MESSAGE: "m7", K.DETAIL_VIA: "bookmark_rewind"})
        milestones.add_milestone(conn, "conv-b", "compact", K.SOURCE_JSONL_SCAN, at_ts="2026-10-10T10:30:00Z", jsonl_line=9,
                                 detail={"trigger": "auto", "pre_tokens": 1234})
        milestones.add_milestone(conn, "conv-b", "rewind", K.SOURCE_PIPELINE, at_ts="2026-10-10T11:00:00Z")
    conn.close()
    monkeypatch.setattr(type(lineage_routes.settings), "get_state_dir", lambda self: state)
    monkeypatch.setattr(bookmark_tools, "_session_uuid_of_row", lambda row_id: uuid)
    return uuid


def _call(args):
    info = SimpleNamespace(session=SimpleNamespace(id="ses_1"), tmux_session="cloude_life", session_row_id=7, host_key="local")

    class View:
        app = None

        async def list_session_infos(self):
            return [info]

    caller = AgentCaller("ses_1", "cloude_life", "ses_1")
    return asyncio.run(tools.call_tool(View(), caller, "session_lineage_get", args))


def test_the_tool_returns_conversations_in_order_with_kinds_split_points_and_milestones(world):
    result = _call({"target": "ses_1"})
    assert not result.get("isError"), result
    body = json.loads(result["content"][0]["text"])
    assert body["session_uuid"] == world
    assert [c["conversation_id"] for c in body["conversations"]] == ["conv-a", "conv-b", "conv-c"]
    by_id = {c["conversation_id"]: c for c in body["conversations"]}
    assert by_id["conv-c"]["current"] is True and by_id["conv-c"]["began"]["kind"] == "rewind"
    assert by_id["conv-c"]["began"]["split"] == {"conversation": "conv-b", "message_uuid": "m7", "line": None}
    assert by_id["conv-b"]["began"]["kind"] == "clear" and by_id["conv-b"]["began"]["from_conversation"] == "conv-a"
    assert [m["kind"] for m in by_id["conv-b"]["milestones"]] == ["compact", "rewind"]
    assert by_id["conv-b"]["milestones"][0]["trigger"] == "auto"


def test_the_tool_is_a_read_and_has_a_short_description():
    assert "session_lineage_get" not in tools.WRITE_TOOLS
    [definition] = [d for d in tools.tool_definitions(None) if d["name"] == "session_lineage_get"]
    assert len(definition["description"]) <= 120
