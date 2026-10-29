
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated

CONVERSATION = "deab833f-3c01-4d80-8340-84d081bb38fa"


@dataclass
class FakeSettings:

    working_dir: Path
    state_dir: Path

    def get_working_dir(self) -> Path:
        return self.working_dir

    def get_state_dir(self) -> Path:
        return self.state_dir


@dataclass
class Rung:

    kind: str = "agent"
    conversation: str = "resumed"


@dataclass
class Preview:

    pane_state: str = "dead"
    projected: Optional[Rung] = None


def resumable(pane_state: str = "dead") -> Preview:
    return Preview(pane_state=pane_state, projected=Rung())


def migrated_state(tmp_path: Path) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    state = ensure_db_migrated(d, 4, "0.0.0")
    assert state.status == "ok", state.message
    return d


def open_conn(state_dir: Path) -> sqlite3.Connection:
    return connect(db_path_for(state_dir))


def add_project(conn: sqlite3.Connection, root: Path, name: str) -> int:
    cur = conn.execute(
        "INSERT INTO projects (root, raw_path, display_name, source, presence, created_at, updated_at) "
        "VALUES (?, ?, ?, 'user', 'unchecked', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
        (str(root), str(root), name))
    conn.commit()
    return int(cur.lastrowid)


def add_session(conn: sqlite3.Connection, working_dir: Path, *, project_id: Optional[int] = None,
                conversation: Optional[str] = CONVERSATION, name: str = "carnivore_mv") -> str:
    uuid = f"sess-{name}"
    conn.execute(
        "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, origin, lifecycle, working_dir, "
        "project_id, project_attribution, claude_session_uuid, agent_family, created_at, updated_at) "
        "VALUES (?, 'cloude', ?, 1700000000, 'created', 'running', ?, ?, 'derived_deepest', ?, 'claude', "
        "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
        (uuid, name, str(working_dir), project_id, conversation))
    conn.commit()
    return uuid


def write_transcript(corpus: Path, folder: Path, conversation: str = CONVERSATION) -> Path:
    encoded = "".join(ch if ch.isalnum() else "-" for ch in str(folder))
    path = corpus / encoded / f"{conversation}.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"type":"user","cwd":"%s"}\n' % folder, encoding="utf-8")
    return path
