
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

import pytest

from src.core import resource_push
from src.core.bookmarks import locate, rows, store
from src.core.lineage import constants as K
from src.core.lineage import ddl, graph, milestones
from src.cplugs.save.port import RestorePoints
from src.cplugs.save.vault import units
from src.cplugs.save.vault.identity import Identity
from src.cplugs.save.vault.store import Vault
from src.cplugs.sdk import transcript_files as tf
from src.cplugs.sdk import ports, restore_points
from tests.python.bookmarks import fixtures
from tests.python.time_machine import helpers as tm_helpers

OLD = tm_helpers.CONV
NOW = datetime(2026, 10, 10, 13, 0, 0, tzinfo=timezone.utc)


def _edge(conn, parent, kind, at, split=None):
    detail = {K.DETAIL_SPLIT_SESSION: split[0], K.DETAIL_SPLIT_MESSAGE: split[1]} if split else None
    graph.add_edge(conn, "conversation", parent, "session", "row-uuid-1", kind, created_at=at, detail=detail)
    graph.add_edge(conn, "conversation", parent, "conversation", fixtures.SOURCE, kind, created_at=at, detail=detail)


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    fixtures.write_transcript(root)
    db = fixtures.make_datastore(tmp_path / "cloude.db")
    with closing(sqlite3.connect(db)) as conn:
        for stmt in ddl.DDL_V49:
            conn.execute(stmt)
        _edge(conn, OLD, "rewind", "2026-10-10T11:00:00Z", split=(OLD, "m7"))
        add = lambda conv, kind, at, **kw: milestones.add_milestone(  # noqa: E731
            conn, conv, kind, K.SOURCE_PIPELINE if kind in ("restart", "sleep") else K.SOURCE_JSONL_SCAN, at_ts=at, **kw)
        add(OLD, "restart", "2026-10-10T10:20:00Z")
        add(OLD, "sleep", "2026-10-10T10:40:00Z")
        add(OLD, "restart", "2026-10-10T10:50:00Z")
        add(fixtures.SOURCE, "restart", "2026-10-10T11:30:00Z")
        add(fixtures.SOURCE, "sleep", "2026-10-10T12:00:00Z")
        add(fixtures.SOURCE, "compact", "2026-10-10T12:30:00Z", jsonl_line=19,
            detail={"record_uuid": "cb", "trigger": "auto", "pre_tokens": 90000})
        conn.commit()
    points = tmp_path / "vault"
    points.mkdir()
    corpus = tm_helpers.make_corpus(tmp_path, conv=OLD, subagents=0)
    vault = Vault(points, on_change=tf.announce_timeline)
    plan = units.plan_claude(units.Sources((corpus,), tmp_path / "codex", tmp_path / "state"), OLD)
    vault.capture(plan, Identity(session_uuid="row-uuid-1", working_dir=tm_helpers.WORKDIR), "kill",
                  now=datetime(2026, 10, 10, 10, 45, tzinfo=timezone.utc))
    monkeypatch.setattr(rows, "db_path", lambda: db)
    ports.register(restore_points.PORT, RestorePoints(lambda: vault))
    monkeypatch.setattr(locate, "_roots", lambda: (root,))
    monkeypatch.setattr(rows, "family_of", lambda agent_type: "codex" if agent_type == "codex" else "claude")
    store.set_store(store.BookmarkStore(tmp_path / "bookmarks.db"))
    store.get_store().add(session_uuid="row-uuid-1", session_row_id=7, claude_session_uuid=fixtures.SOURCE,
                          entry_uuid="u2", label="the second ask", created_by="owner", snippet="second prompt",
                          entry_timestamp="2026-10-10T12:10:00Z")
    yield {"db": db, "points": points, "vault": vault, "plan": plan, "tmp": tmp_path, "root": root}
    ports.unregister(restore_points.PORT)
    store.set_store(None)


@pytest.fixture
def pushed(monkeypatch):
    seen: list = []
    monkeypatch.setattr(resource_push, "notify", lambda topic: seen.append(topic))
    return seen


def dump(value) -> str:
    return json.dumps(value, indent=1, sort_keys=True, default=str)
