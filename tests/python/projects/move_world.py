
from __future__ import annotations

import json
import os
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from src.core.claude_transcript_correlate import slugify_project_dir as enc
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.project_move import claude_side
from src.core.project_move.plan import MovePlan, PaneListing, build_plan
from src.core.project_writes import create_project
from src.core.session_journal_store import JOURNAL_SCHEMA, journal_path

NO_PANES = PaneListing(ok=True)


def add_session(conn: Any, uuid: str, working_dir: str, lifecycle: str = "stopped", name: str = "",
                epoch: int = 0) -> None:
    conn.execute(
        "INSERT INTO sessions (session_uuid, working_dir, origin, lifecycle, tmux_name, tmux_created_epoch,"
        " created_at, updated_at) VALUES (?, ?, 'created', ?, ?, ?, 'now', 'now')",
        (uuid, working_dir, lifecycle, name or uuid, epoch))


def build_world(tmp_path: Path, monkeypatch: Any) -> SimpleNamespace:
    from src.config import settings

    base = tmp_path.resolve()
    state = base / "state"
    state.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    monkeypatch.setattr(type(settings), "get_working_dir", lambda self: base, raising=True)
    monkeypatch.setattr(settings, "auth_config_file", str(base / "config.json"), raising=False)
    monkeypatch.setattr(settings, "_auth_config_cache", None, raising=False)
    assert ensure_db_migrated(state, 4, "0.0.0").status == "ok"
    db = db_path_for(state)
    old, sub, sibling = base / "dev" / "alpha", base / "dev" / "alpha" / "sub", base / "dev" / "alpha_x"
    for folder in (sub, sibling, base / "org"):
        folder.mkdir(parents=True)
    (old / "notes.md").write_text("x")
    (old / ".claude").mkdir()
    (old / ".claude" / "settings.json").write_text(json.dumps({"allow": [f"Read({old}/**)"]}))
    with closing(connect(db)) as conn:
        alpha = create_project(conn, name="alpha", path=str(old))
        child = create_project(conn, name="sub", path=str(sub))
        other = create_project(conn, name="alpha_x", path=str(sibling))
        add_session(conn, "s-root", str(old))
        add_session(conn, "s-sub", str(sub / "deep"))
        add_session(conn, "s-sibling", str(sibling))
        conn.execute("INSERT INTO conversation_index (conversation_id, working_dir, captured_at, updated_at)"
                     " VALUES ('c1', ?, 'now', 'now'), ('c2', ?, 'now', 'now')", (str(sub), str(sibling)))
    projects = base / "claude" / "projects"
    for folder in (old, sub, sibling):
        (projects / enc(str(folder))).mkdir(parents=True)
        (projects / enc(str(folder)) / "t.jsonl").write_text("{}\n")
    home = base / "home"
    home.mkdir()
    (home / "Development").symlink_to(base / "dev")
    monkeypatch.setenv("HOME", str(home))
    short = projects / enc(str(home / "Development" / "alpha"))
    (short / "memory").mkdir(parents=True)
    (short / "short.jsonl").write_text("{}\n")
    (short / "memory" / "b.md").write_text("b")
    (projects / enc(str(old)) / "memory").mkdir()
    (projects / enc(str(old)) / "memory" / "a.md").write_text("a")
    trust = base / "claude.json"
    trust.write_text(json.dumps({"projects": {str(old): {"secret_ish": "never echoed"}}}))
    jp = journal_path(state)
    jp.parent.mkdir(parents=True)
    jp.write_text(json.dumps({"schema": JOURNAL_SCHEMA, "sessions": {"k": {"cwd": str(sub), "working_dir": str(sibling)}},
                              "offer": {"candidates": [{"folder": str(old)}]}}))
    monkeypatch.setattr(claude_side, "transcript_roots", lambda: (projects,))
    monkeypatch.setattr(claude_side, "claude_json_files", lambda config_path=None: [trust])
    return SimpleNamespace(base=base, state=state, db=db, old=old, sub=sub, sibling=sibling, new=base / "org" / "alpha",
                           projects=projects, short=short, ids={"alpha": alpha["id"], "sub": child["id"], "alpha_x": other["id"]})


def plan_for(w: SimpleNamespace, move_folder: bool, panes: PaneListing = NO_PANES, new_root: Optional[str] = None,
             **kwargs: Any) -> MovePlan:
    from src.config import settings

    with closing(connect(w.db, create=False)) as conn:
        row = dict(conn.execute("SELECT * FROM projects WHERE id = ?", (w.ids["alpha"],)).fetchone())
        return build_plan(conn, row, str(w.new) if new_root is None else new_root, move_folder, panes=panes,
                          settings=settings, **kwargs)


def snapshot(w: SimpleNamespace) -> tuple:
    with closing(connect(w.db, create=False)) as conn:
        rows = (
            sorted(tuple(r) for r in conn.execute("SELECT id, root, raw_path FROM projects")),
            sorted(tuple(r) for r in conn.execute("SELECT session_uuid, working_dir FROM sessions")),
            sorted(tuple(r) for r in conn.execute("SELECT conversation_id, working_dir FROM conversation_index")),
        )
    return rows, sorted(os.listdir(w.projects)), os.path.isdir(w.old), journal_path(w.state).read_text()
