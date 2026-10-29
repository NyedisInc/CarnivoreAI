
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import List

SOURCE = "11111111-1111-4111-8111-111111111111"
CWD = "/tmp/bookmark-fixture-project"


def _rec(kind: str, uuid: str, parent, **extra) -> dict:
    base = {"parentUuid": parent, "isSidechain": False, "type": kind, "uuid": uuid, "sessionId": SOURCE,
            "timestamp": f"2026-10-06T00:00:{len(uuid):02d}Z", "cwd": CWD, "userType": "external",
            "version": "2.1.292", "gitBranch": "main"}
    base.update(extra)
    return base


def _user(uuid: str, parent, text: str, **extra) -> dict:
    return _rec("user", uuid, parent, message={"role": "user", "content": text}, **extra)


def _result(uuid: str, parent, tool_id: str) -> dict:
    return _rec("user", uuid, parent, toolUseResult={"ok": True}, message={"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": "ok"}]})


def _assistant(uuid: str, parent, msg_id: str, block: dict) -> dict:
    return _rec("assistant", uuid, parent, message={"role": "assistant", "id": msg_id, "content": [block]})


def records() -> List[dict]:
    tool = lambda i: {"type": "tool_use", "id": i, "name": "Bash", "input": {}}  # noqa: E731
    text = lambda t: {"type": "text", "text": t}  # noqa: E731
    return [
        {"type": "permission-mode", "permissionMode": "default", "sessionId": SOURCE},
        _user("u1", None, "first prompt"),
        _assistant("a1a", "u1", "m1", text("looking")),
        _assistant("a1b", "a1a", "m1", tool("t1")),
        _assistant("a1c", "a1b", "m1", tool("t2")),
        _result("r1", "a1b", "t1"),
        _result("r2", "a1c", "t2"),
        _assistant("a2", "r2", "m2", text("done one")),
        _rec("system", "sys1", "a2", subtype="turn_duration", durationMs=5),
        _user("ab1", "sys1", "abandoned prompt"),
        _assistant("ab2", "ab1", "mab", text("abandoned answer")),
        _rec("user", "side1", None, isSidechain=True, message={"role": "user", "content": "sub-agent task"}),
        {"type": "progress", "uuid": "prog", "parentUuid": "sys1", "sessionId": SOURCE, "isSidechain": False},
        _user("u2", "prog", "second prompt"),
        _assistant("a3", "u2", "m3", tool("t3")),
        _result("r3", "a3", "t3"),
        _assistant("a4", "r3", "m4", text("done two")),
        {"type": "content-replacement", "sessionId": SOURCE, "replacements": [{"toolUseId": "t3", "path": "x"}]},
        _rec("system", "cb", None, subtype="compact_boundary", logicalParentUuid="a4", content="compacted"),
        _user("cs", "cb", "summary of before", isCompactSummary=True),
        _user("u3", "cs", "third prompt"),
        _assistant("a5", "u3", "m5", text("done three")),
    ]


def write_transcript(root: Path, conversation: str = SOURCE, cwd: str = CWD) -> Path:
    from src.core.claude_transcript_correlate import slugify_project_dir

    folder = root / slugify_project_dir(cwd)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{conversation}.jsonl"
    path.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records()), encoding="utf-8")
    return path


def make_datastore(path: Path, *, agent_type: str = "claude", conversation: str = SOURCE,
                   tmux_name: str = "cloude_fixture", session_uuid: str = "row-uuid-1") -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE sessions (id INTEGER PRIMARY KEY, session_uuid TEXT, claude_session_uuid TEXT, "
        "claude_session_uuid_source TEXT, working_dir TEXT, title TEXT, tmux_name TEXT, tmux_socket TEXT, "
        "tmux_created_epoch INTEGER, agent_type TEXT, model TEXT, launch_record TEXT, host_key TEXT, updated_at TEXT);"
        "CREATE UNIQUE INDEX ux_sessions_claude_uuid ON sessions (claude_session_uuid) "
        "WHERE claude_session_uuid IS NOT NULL;")
    conn.execute("INSERT INTO sessions (id, session_uuid, claude_session_uuid, claude_session_uuid_source, working_dir, "
                 "title, tmux_name, tmux_socket, tmux_created_epoch, agent_type, host_key) "
                 "VALUES (7, ?, ?, 'registry', ?, 'api', ?, 'test_sock', 100, ?, 'local')",
                 (session_uuid, conversation, CWD, tmux_name, agent_type))
    conn.commit()
    conn.close()
    return path


def row_conversation(path: Path) -> tuple:
    conn = sqlite3.connect(path)
    try:
        return tuple(conn.execute("SELECT claude_session_uuid, claude_session_uuid_source FROM sessions WHERE id = 7").fetchone())
    finally:
        conn.close()
