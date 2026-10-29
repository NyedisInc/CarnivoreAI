
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from src.core.app_alerts import service
from src.core.db import db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.transcript_source.locate import locate
from src.core.transcript_manifest import condition, lookup
from src.core.transcript_manifest import constants as K
from src.core.transcript_manifest import scan as scan_mod

A, B, C = ("aaaaaaaa-0000-0000-0000-00000000000a", "aaaaaaaa-0000-0000-0000-00000000000b",
           "aaaaaaaa-0000-0000-0000-00000000000c")
AGENT = "agent-1a2b3c4d"


def _line(serial: str) -> bytes:
    return json.dumps({"type": "user", "uuid": serial, "cwd": "/Users/x/moved-away"}).encode() + b"\n"


def _rows(db: Path) -> dict:
    with closing(sqlite3.connect(db)) as conn:
        conn.row_factory = sqlite3.Row
        return {Path(r["path"]).name: dict(r) for r in conn.execute(f"SELECT * FROM {K.TABLE}")}


def test_manifest_classifies_every_change_and_capture_finds_the_real_path(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    db = db_path_for(state)
    service.configure(db, None)
    service.raise_alert(K.REMOVED_ALERT_KEY, source=K.ALERT_SOURCE, severity="warn", title_key="app_alert.transcripts.removed.title",
                        sticky=True, auto_resolve=False)
    service.raise_alert(K.RETIRED_FRESHNESS_ALERT_KEY, source="archive_freshness", severity="warn",
                        title_key="app_alert.archive.freshness.check_failed.title", sticky=True, auto_resolve=False)
    assert len(service.list_view(db, include_closed=False, limit=20)["alerts"]) == 2
    condition.install(state)
    assert not [r for r in service.list_view(db, include_closed=False, limit=20)["alerts"]
                if r["key"] in (K.REMOVED_ALERT_KEY, K.RETIRED_FRESHNESS_ALERT_KEY)]
    condition.uninstall()
    corpus = tmp_path / "projects"
    slug = corpus / "-Users-x-old-name"
    (slug / A / "subagents").mkdir(parents=True)
    a, b, c, agent = slug / f"{A}.jsonl", slug / f"{B}.jsonl", slug / f"{C}.jsonl", slug / f"{AGENT}.jsonl"
    a.write_bytes(_line("a1") + _line("a2"))
    b.write_bytes(_line("b1") + _line("b2"))
    c.write_bytes(_line("c1"))
    agent.write_bytes(_line("g1") + b'{"partial": ')
    (slug / A / "subagents" / "agent-sub.jsonl").write_bytes(_line("s1"))

    reads: list = []
    real_read = scan_mod.read_last_line
    monkeypatch.setattr(scan_mod, "read_last_line", lambda p, size, **kw: reads.append(Path(p).name) or real_read(p, size, **kw))

    def scan_now():
        reads.clear()
        record = condition.run_scan(state, claude_roots=(corpus,), codex_home="")
        assert record["status"] == "ok", record
        return record

    first = scan_now()
    assert first[K.OUT_ADDED] == 5
    rows = _rows(db)
    assert rows[a.name]["last_line_uuid"] == "a2" and rows[a.name]["last_line_offset"] == len(_line("a1"))
    assert rows[a.name]["complete_bytes"] == a.stat().st_size and rows[a.name]["kind"] == K.KIND_CONVERSATION
    assert rows[agent.name]["last_line_uuid"] == "g1" and rows[agent.name]["complete_bytes"] == len(_line("g1"))
    assert rows["agent-sub.jsonl"]["kind"] == K.KIND_SUBAGENT and rows["agent-sub.jsonl"]["conversation_id"] == A

    second = scan_now()
    assert second[K.OUT_UNCHANGED] == 5 and reads == []

    old_size = a.stat().st_size
    a.write_bytes(a.read_bytes() + _line("a3"))
    b.write_bytes(_line("x1") + _line("x2") + _line("x3"))
    c.unlink()
    third = scan_now()
    assert (third[K.OUT_GROWN], third[K.OUT_REWRITTEN], third[K.OUT_REMOVED]) == (1, 1, 1)
    rows = _rows(db)
    grown = rows[a.name]
    assert grown["status"] == K.STATUS_GROWN and grown["last_line_uuid"] == "a3"
    assert (grown["prev_size"], grown["prev_last_line_uuid"]) == (old_size, "a2")
    assert grown["prev_last_line_offset"] == len(_line("a1")) and grown["prev_complete_bytes"] == old_size
    assert rows[b.name]["status"] == K.STATUS_REWRITTEN
    assert rows[c.name]["status"] == K.STATUS_GONE and rows[c.name]["gone_at"]
    assert not [r for r in service.list_view(db, include_closed=False, limit=20)["alerts"]
                if r["key"] == K.REMOVED_ALERT_KEY]

    placeholder = slug / "dddddddd-0000-0000-0000-00000000000d.jsonl"
    placeholder.write_bytes(_line("d1"))
    real_lstat = os.lstat

    def fake_lstat(path):
        st = real_lstat(path)
        if Path(path) == placeholder:
            return SimpleNamespace(st_size=st.st_size, st_mtime_ns=st.st_mtime_ns, st_flags=K.SF_DATALESS)
        return st

    monkeypatch.setattr(scan_mod, "_lstat", fake_lstat)
    fourth = scan_now()
    assert fourth[K.OUT_DATALESS] == 1 and placeholder.name not in reads
    assert _rows(db)[placeholder.name]["dataless"] == 1 and _rows(db)[placeholder.name]["last_line_uuid"] is None

    try:
        lookup.configure(db)
        found = locate("claude", AGENT, "/Users/x/moved-away")
    finally:
        lookup.configure(None)
    assert found is not None and found.transcript == agent
    condition.uninstall()
