
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import transaction
from src.core.db_models import SESSION_ORIGIN_ADOPTED
from src.core.lineage import backfill, events, graph, scan, view
from src.core.session_claude_correlate_bind import bind_correlated_uuid
from src.core.session_identity import record_instance
from tests.s7_helpers import TEST_SOCKET, migrated_connection, session_row

PARENT = "5c2b9059-0000-4000-8000-000000000000"
CHILDREN = [f"{n}{n}{n}{n}{n}{n}{n}{n}-0000-4000-8000-00000000000{n}" for n in range(1, 6)]
COMPACTED = "cccccccc-0000-4000-8000-000000000000"
BOUNDARY = {"type": "system", "subtype": "compact_boundary", "sessionId": COMPACTED, "uuid": "u-boundary",
            "logicalParentUuid": "u-before", "timestamp": "2026-09-01T12:00:00Z",
            "compactMetadata": {"trigger": "auto", "preTokens": 150000}}


@pytest.fixture()
def conn(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    connection = migrated_connection(state)
    yield connection
    connection.close()


def test_a_parent_forked_into_five_sessions_is_previous_under_each_and_they_are_siblings(conn):
    uuids = []
    with transaction(conn):
        for i, child in enumerate(CHILDREN):
            name = f"cloude_fork{i}"
            record_instance(conn, socket=TEST_SOCKET, name=name, epoch=1_800_000_000 + i, origin=SESSION_ORIGIN_ADOPTED,
                            working_dir="/tmp/fork-proj")
            bind_correlated_uuid(conn, socket=TEST_SOCKET, name=name, epoch=1_800_000_000 + i, claude_uuid=child)
            uuids.append(session_row(conn, name)["session_uuid"])
            events.record_flip_edges(conn, PARENT, uuids[-1], "fork", child_conversation_id=child)
    for uuid in uuids:
        previous = graph.previous_conversations(conn, uuid, _current(conn, uuid))
        assert [e["parent_id"] for e in previous] == [PARENT] and previous[0]["edge_kind"] == "fork"
        siblings = {s["node_id"] for s in view.neighbourhood(conn, "session", uuid)["siblings"]}
        assert siblings == set(uuids) - {uuid}
    assert graph.previous_counts(conn) == {uuid: 1 for uuid in uuids}
    kids = {s["node_id"] for s in graph.siblings_of(conn, "conversation", CHILDREN[0])}
    assert kids == set(CHILDREN[1:])


def _current(conn, uuid):
    return conn.execute("SELECT claude_session_uuid FROM sessions WHERE session_uuid = ?", (uuid,)).fetchone()[0]


def test_a_compact_boundary_is_a_milestone_from_the_live_jsonl_scan(conn, tmp_path):
    other = "dddddddd-0000-4000-8000-000000000000"
    corpus = tmp_path / "projects"
    (corpus / "-tmp-proj").mkdir(parents=True)
    lines = [{"type": "user", "timestamp": "2026-09-01T10:00:00Z", "entrypoint": "sdk-cli"}, {**BOUNDARY, "sessionId": other}]
    (corpus / "-tmp-proj" / f"{other}.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    found = backfill.plan(conn, disk_roots=scan.roots(corpus))
    [hit] = found.compacts
    assert (hit["conversation_id"], hit["jsonl_line"], hit["source"]) == (other, 2, "jsonl_scan")
    assert hit["detail"]["trigger"] == "auto"
    with transaction(conn):
        assert backfill.apply(conn, found)["compacts_added"] == 1
    assert graph.levels_of(conn, [("conversation", other)]) == {f"conversation:{other}": "subsession"}
