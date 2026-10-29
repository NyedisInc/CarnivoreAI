
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated

CONV = "11111111-2222-3333-4444-555555555555"
UUID = "sess-uuid-purge-0001"
NAME = "carnivore_purgeme"
EPOCH = 1700000000
TITLE = "purge me"
SECRET_LINE = '{"text":"transcript body that must never reach a receipt"}\n'


def insert(conn: sqlite3.Connection, table: str, **values: Any) -> int:
    for col in conn.execute(f"PRAGMA table_info('{table}')").fetchall():
        name, ctype, notnull, default, pk = col[1], (col[2] or "").upper(), col[3], col[4], col[5]
        if name in values or not notnull or default is not None or pk:
            continue
        values[name] = 0 if "INT" in ctype else "x"
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    return int(conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(values.values())).lastrowid)


def add_session(conn: sqlite3.Connection, uuid: str, name: str, conv: str | None, epoch: int = EPOCH,
                title: str | None = None, parent: int | None = None) -> int:
    return insert(conn, "sessions", session_uuid=uuid, working_dir="/w/proj", origin="created", lifecycle="stopped",
                  tmux_name=name, tmux_created_epoch=epoch, claude_session_uuid=conv, title=title,
                  parent_session_id=parent, created_at="now", updated_at="now")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _seed_db(conn: sqlite3.Connection) -> int:
    row = add_session(conn, UUID, NAME, CONV, title=TITLE)
    conn.execute("INSERT INTO session_notes (session_uuid, body, revision, updated_at) VALUES (?, 'n', 1, 'now')",
                 (UUID,))
    group = insert(conn, "session_groups", group_uuid="g1", name="g", position=0, created_at="now", updated_at="now")
    conn.execute("INSERT INTO session_group_membership (session_uuid, group_id, position, added_at) "
                 "VALUES (?, ?, 0, 'now')", (UUID, group))
    insert(conn, "conversation_index", conversation_id=CONV, session_uuid=UUID, captured_at="now", updated_at="now")
    insert(conn, "transcript_files", path=f"/h/.claude/projects/-w-proj/{CONV}.jsonl", conversation_id=CONV,
           family="claude", root="r", kind="conversation", status="present")
    archive = insert(conn, "transcript_archives", archive_uuid="a1", kind="session", claude_session_uuid=CONV,
                     source_path=f"-w-proj/{CONV}.jsonl", root_session_id=row, line_ending="LF",
                     has_trailing_newline=1, root_state="rooted", growth_kind="initial")
    insert(conn, "transcript_records", archive_id=archive, line_no=1, byte_offset=0, byte_length=1, status="ok")
    return row


def build(tmp_path: Path, monkeypatch: Any) -> SimpleNamespace:
    from src.config import settings
    from src.core.inventory import file_trace

    base = tmp_path.resolve()
    state = base / "state"
    state.mkdir()
    config = base / "config.json"
    pins = base / "pinned_themes.json"
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    monkeypatch.setattr(type(settings), "get_pinned_themes_path", lambda self: pins, raising=True)
    monkeypatch.setattr(settings, "auth_config_file", str(config), raising=False)
    monkeypatch.setattr(settings, "_auth_config_cache", None, raising=False)
    monkeypatch.setenv("HOME", str(base / "home"))
    assert ensure_db_migrated(state, 4, "0.0.0").status == "ok"
    with closing(connect(db_path_for(state))) as conn:
        row = _seed_db(conn)
    home = base / "claude"
    files: Dict[str, Path] = {
        "transcript": home / "projects" / "-w-proj" / f"{CONV}.jsonl",
        "short_spelling_subagent": home / "projects" / "-Users-x-Development-proj" / CONV / "subagents" / "agent-a.jsonl",
        "todo": home / "todos" / f"{CONV}-agent-{CONV}.json",
        "file_history": home / "file-history" / CONV / "f1",
        "session_env": home / "session-env" / CONV / "e1",
        "debug": home / "debug" / f"{CONV}.txt",
        "registry": home / "sessions" / "4242.json",
        "codex": base / "codex" / "sessions" / "2026" / "10" / "09" / f"rollout-2026-10-09T00-00-00-{CONV}.jsonl",
    }
    for key, path in files.items():
        _write(path, json.dumps({"sessionId": CONV}) if key == "registry" else SECRET_LINE)
    keep = home / "projects" / "-w-proj" / "other-conversation.jsonl"
    _write(keep, "{}\n")
    _write(home / "sessions" / "77.json", json.dumps({"sessionId": "someone-else"}))
    _write(home / "history.jsonl", json.dumps({"display": "hi", "sessionId": CONV}) + "\n")
    monkeypatch.setattr(file_trace, "claude_homes", lambda: [home])
    monkeypatch.setenv("CODEX_HOME", str(base / "codex"))
    with closing(sqlite3.connect(state / "bookmarks.db")) as side:
        side.execute("CREATE TABLE bookmarks (id INTEGER PRIMARY KEY, session_uuid TEXT, session_row_id INTEGER, "
                     "claude_session_uuid TEXT)")
        side.execute("INSERT INTO bookmarks (session_uuid, session_row_id, claude_session_uuid) VALUES (?, ?, ?)",
                     (UUID, row, CONV))
        side.execute("INSERT INTO bookmarks (session_uuid, session_row_id, claude_session_uuid) VALUES "
                     "('other', 9, 'other-conv')")
        side.commit()
    with closing(sqlite3.connect(state / "attention_history.db")) as side:
        side.execute("CREATE TABLE attention_events (session_uuid TEXT, kind TEXT, at TEXT)")
        side.execute("INSERT INTO attention_events VALUES (?, 'question', 'now')", (UUID,))
        side.commit()
    layout_key = f"{NAME}:{EPOCH}"
    config.write_text(json.dumps({"ui_preferences": {"schema_version": 1, "revision": 3, "values": {
        "drawer_arrangement": {"v": 1, "pinned": [UUID, "keep-me"], "order": [UUID], "bands": {"g:x": [UUID, "o"]}},
        "terminal_layouts": {"v": 1, "sessions": {layout_key: {"layout": {"v": 1, "rows": [1]}},
                                                   "other:1": {"layout": {"v": 1, "rows": [f"terminal:row:{row}"]}}}},
    }}}))
    journal = state / "session-journal" / "journal.json"
    _write(journal, json.dumps({"schema": 1, "sessions": {"k1": {"session_uuid": UUID}, "k2": {"session_uuid": "x"}},
                                "declined": {}, "offer": None}))
    return SimpleNamespace(base=base, state=state, config=config, home=home, files=files, keep=keep, row=row,
                           journal=journal, db=db_path_for(state))
