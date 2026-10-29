
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import session_timeline_routes
from src.api.auth import require_auth
from src.core.bookmarks.errors import SessionNotFound
from src.core.session_timeline import gather
from tests.python.bookmarks import fixtures
from tests.python.session_timeline.conftest import NOW, OLD


def _build(env):
    return gather.build("7", now=NOW)


def test_bars_are_in_the_order_lived_and_spans_meet_at_the_rewind(env):
    out = _build(env)
    assert [b["conversation_id"] for b in out["bars"]] == [OLD, fixtures.SOURCE]
    old, current = out["bars"]
    assert current["current"] and not old["current"]
    assert current["began"]["kind"] == "rewind" and current["began"]["split"]["message_uuid"] == "m7"
    assert old["ended_at"] == current["started_at"] and current["started_at"].startswith("2026-10-10T11:00:00")
    assert current["ended_at"] == NOW.isoformat()
    assert out["session_row_id"] == 7 and out["current_conversation"] == fixtures.SOURCE


def test_marks_cover_every_kind_and_are_oldest_first(env):
    marks = _build(env)["marks"]
    kinds = [m["kind"] for m in marks]
    assert set(kinds) == {"restart", "restore", "bookmark", "compact"}
    times = [m["at"] for m in marks]
    assert times == sorted(times)
    compact = next(m for m in marks if m["kind"] == "compact")
    assert compact["pre_tokens"] == 90000 and compact["trigger"] == "auto" and compact["entry_uuid"] == "cb" and compact["can_peek"]
    bookmark = next(m for m in marks if m["kind"] == "bookmark")
    assert bookmark["label"] == "the second ask" and bookmark["entry_uuid"] == "u2" and bookmark["bookmark_id"]
    restore = next(m for m in marks if m["kind"] == "restore")
    assert restore["conversation_id"] == OLD and restore["reason"] == "kill" and restore["point_id"].endswith("-kill") and restore["failsafe"] is False
    assert [m["conversation_id"] for m in marks if m["kind"] == "restart"] == [OLD, OLD, fixtures.SOURCE]


def test_a_sleep_ends_at_the_next_sign_of_life_and_the_last_one_stays_open(env):
    gaps = _build(env)["gaps"]
    assert [(g["conversation_id"], g["end"] is None) for g in gaps] == [(OLD, False), (fixtures.SOURCE, True)]
    assert gaps[0]["end"].startswith("2026-10-10T10:50:00")
    assert gaps[1]["open"] is True


def test_a_split_point_is_dated_from_the_transcript_it_was_cut_from(env, monkeypatch):
    from src.core.lineage import graph
    import sqlite3
    from contextlib import closing

    new = "conv-new"
    with closing(sqlite3.connect(env["db"])) as conn:
        graph.add_edge(conn, "conversation", fixtures.SOURCE, "session", "row-uuid-1", "fork", created_at="2026-10-10T12:45:00Z",
                       detail={"forked_from_session": fixtures.SOURCE, "forked_from_message_uuid": "u2"})
        graph.add_edge(conn, "conversation", fixtures.SOURCE, "conversation", new, "fork", created_at="2026-10-10T12:45:00Z",
                       detail={"forked_from_session": fixtures.SOURCE, "forked_from_message_uuid": "u2"})
        conn.execute("UPDATE sessions SET claude_session_uuid = ? WHERE id = 7", (new,))
        conn.commit()
    out = _build(env)
    child = out["bars"][-1]
    assert child["conversation_id"] == new and child["began"]["kind"] == "fork"
    assert child["began"]["split"]["at"] == "2026-10-06T00:00:02Z"


def test_a_session_with_no_lineage_is_one_bare_bar(env):
    from src.core.lineage import ddl
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(env["db"])) as conn:
        for table in ("lineage_edges", "lineage_nodes", "conversation_milestones"):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
    out = _build(env)
    assert [b["conversation_id"] for b in out["bars"]] == [fixtures.SOURCE] and out["gaps"] == []
    assert [m["kind"] for m in out["marks"]] == ["bookmark"]
    assert ddl


def test_an_unknown_session_is_not_found(env):
    with pytest.raises(SessionNotFound):
        gather.build("99", now=NOW)


@pytest.fixture
def client(env, monkeypatch):
    monkeypatch.setattr(gather, "_db_path", lambda: env["db"])
    app = FastAPI()
    app.include_router(session_timeline_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: "owner"
    return TestClient(app)


def test_the_route_answers_by_row_id_and_by_session_uuid(client):
    by_id = client.get("/api/v1/sessions/7/timeline").json()
    by_uuid = client.get("/api/v1/sessions/row-uuid-1/timeline").json()
    assert by_id["session_uuid"] == "row-uuid-1" and by_id["bars"][0]["conversation_id"] == by_uuid["bars"][0]["conversation_id"]
    assert client.get("/api/v1/sessions/99/timeline").status_code == 404


def test_the_peek_returns_the_messages_up_to_the_point_and_refuses_a_stranger_conversation(client):
    ok = client.get(f"/api/v1/sessions/7/timeline/peek?conversation={fixtures.SOURCE}&entry_uuid=a5&turns=2").json()
    assert [(p["role"], p["text"]) for p in ok["parts"]] == [("user", "third prompt"), ("assistant", "done three")]
    stray = client.get(f"/api/v1/sessions/7/timeline/peek?conversation=someone-elses&entry_uuid=a5")
    assert stray.status_code == 404 and stray.json()["detail"]["code"] == "entry_not_found"
    gone = client.get(f"/api/v1/sessions/7/timeline/peek?conversation={fixtures.SOURCE}&entry_uuid=nope")
    assert gone.status_code == 404
    assert client.get("/api/v1/sessions/7/timeline/peek?conversation=x").status_code == 422


def test_a_running_session_has_no_open_sleep_gap(env):
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(env["db"])) as conn:
        conn.execute("ALTER TABLE sessions ADD COLUMN lifecycle TEXT")
        conn.execute("ALTER TABLE sessions ADD COLUMN archived_at TEXT")
        conn.execute("UPDATE sessions SET lifecycle = 'running' WHERE id = 7")
        conn.commit()
    gaps = _build(env)["gaps"]
    assert [g["open"] for g in gaps] == [False, False]
    assert gaps[1]["end"] == NOW.isoformat()
