
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.core.bookmarks.store import DB_FILENAME, BookmarkStore
from tests.python.deepsearch.helpers import build_world, drain, go_ready, mount, rec, scan, teardown
from tests.python.transcript_source.helpers import CONV

SECRET = "ghp_" + "aB3xY9" * 6
BASE = "/api/v1/deepsearch"


def _t(minute: int) -> str:
    return f"2026-10-12T10:{minute:02d}:00.000Z"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    built = build_world(tmp_path, monkeypatch)
    built["main"].write_bytes(b"".join([
        rec(0, "kickoff the work", timestamp=_t(0)),
        rec(1, "step one of zebrafind", "assistant", timestamp=_t(1)),
        rec(2, "zebrafind again please", timestamp=_t(5)),
        rec(3, "second reply", "assistant", timestamp=_t(6)),
        rec(4, f"later, key {SECRET}", timestamp=_t(30)),
        rec(5, "all donezo now", "assistant", timestamp=_t(31)),
    ]))
    marks = BookmarkStore(built["state"] / DB_FILENAME)
    for entry, minute in (("u-3", 6), ("u-4", 30)):
        marks.add(session_uuid="sess-uuid-1", session_row_id=1, claude_session_uuid=CONV, entry_uuid=entry,
                  label=f"mark {minute}", created_by="owner", entry_timestamp=_t(minute))
    app = mount(built, monkeypatch)
    scan(built)
    drain(built)
    go_ready(built)
    built["app"] = app
    yield built
    teardown()


def _search(client, word):
    return client.get(f"{BASE}/search", params={"q": word, "per_group": 5}).json()["groups"][0]["hits"]


def test_hits_carry_their_own_time_and_the_earliest_bookmark_at_or_after(world):
    with TestClient(world["app"]) as client:
        by_line = {h["line"]: h for h in _search(client, "zebrafind")}
        assert by_line[1]["at"] == _t(1) and by_line[2]["at"] == _t(5)
        assert by_line[1]["bookmark"] == {"id": 1, "label": "mark 6", "at": _t(6)}
        assert by_line[2]["bookmark"]["id"] == 1
        (last,) = _search(client, "donezo")
        assert last["at"] == _t(31) and last["bookmark"] is None


def test_context_window_orders_pages_redacts_and_marks_bookmarks(world):
    with TestClient(world["app"]) as client:
        around = client.get(f"{BASE}/context", params={"conversation_id": CONV, "line": 2, "before": 1, "after": 1}).json()
        assert [m["line"] for m in around["messages"]] == [1, 2, 3] and around["anchor"] == 2
        assert [m["role"] for m in around["messages"]] == ["assistant", "user", "assistant"]
        assert around["messages"][1]["at"] == _t(5) and around["has_before"] is True and around["has_after"] is True
        assert [(b["id"], b["after_line"]) for b in around["bookmarks"]] == [(1, 3)]
        older = client.get(f"{BASE}/context", params={"conversation_id": CONV, "before_line": 1, "before": 5}).json()
        assert [m["line"] for m in older["messages"]] == [0] and older["has_before"] is False
        newer = client.get(f"{BASE}/context", params={"conversation_id": CONV, "after_line": 3, "after": 5}).json()
        assert [m["line"] for m in newer["messages"]] == [4, 5] and newer["has_after"] is False
        assert SECRET not in newer["messages"][0]["text"] and "****" in newer["messages"][0]["text"]
        assert [b["id"] for b in newer["bookmarks"]] == [2]
        at = client.get(f"{BASE}/context", params={"conversation_id": CONV, "at": _t(30), "before": 1, "after": 1}).json()
        assert at["anchor"] == 4
        assert client.get(f"{BASE}/context", params={"conversation_id": CONV, "line": 99}).status_code == 404
        assert client.get(f"{BASE}/context", params={"conversation_id": "nope", "line": 1}).status_code == 404
        two = client.get(f"{BASE}/context", params={"conversation_id": CONV, "line": 1, "at": _t(1)})
        assert two.status_code == 422


def test_context_refuses_a_caller_who_is_not_signed_in(world):
    world["app"].dependency_overrides.clear()
    with TestClient(world["app"]) as client:
        assert client.get(f"{BASE}/context", params={"conversation_id": CONV, "line": 1}).status_code in (401, 403)
