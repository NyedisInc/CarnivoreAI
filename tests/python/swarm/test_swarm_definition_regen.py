
from __future__ import annotations

import asyncio
from contextlib import closing
from types import SimpleNamespace

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.swarm import body, body_create, definition, memory, say, store

OLD = "---\nname: old\n---\n\nYou are X. Answer the owner with pack_say. Hand changes over through pack_spawn.\n"


def test_a_definition_with_old_text_gets_the_current_template_on_the_next_wake(tmp_path, monkeypatch):
    from src.api import recreate_action
    from src.config import settings

    state, repo = tmp_path / "state", tmp_path / "repo"
    state.mkdir()
    repo.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    assert ensure_db_migrated(state).status == "ok"
    with closing(connect(db_path_for(state), create=False)) as conn:
        conn.execute("INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, working_dir, title, origin,"
                     " lifecycle, created_at, updated_at) VALUES ('uuid-loki', 'cloude', 'cloude_loki', 1788821572, ?, 't', 'created',"
                     " 'running', '2026-03-01T00:00:00Z', '2026-09-08T00:00:00Z')", (str(repo),))
        row_id = conn.execute("SELECT id FROM sessions WHERE session_uuid = 'uuid-loki'").fetchone()[0]
        boss = store.create_agent(conn, slug="odin", rank="project", job="repo", display_name="Odin Prime", effort="high",
                                  repo_dir=str(repo))
        loki = store.create_agent(conn, slug="loki", rank="feature", job="swap models", display_name="Loki", effort="medium",
                                  repo_dir=str(repo), parent_id=boss["id"], goal="swap the checkout model")
        store.set_session_row(conn, loki["id"], row_id)
        loki = store.get_agent(conn, loki["id"])
    body_create.write_files(state, loki, "Odin Prime")
    defn, twin = repo / ".claude" / "agents" / "loki.md", repo / ".codex" / "agents" / "loki.toml"
    current_defn, current_twin = defn.read_text(), twin.read_text()
    mem = memory.memory_dir(repo, "loki", "project")
    note = mem / "note.md"
    note.write_text("a fact the agent kept\n")
    index = (mem / "MEMORY.md").read_text()
    defn.write_text(OLD)
    twin.write_text('name = "old"\ndescription = "old"\ndeveloper_instructions = "Answer with pack_say."\n')
    seen = []

    async def recreate(uuid, agent_type, *, get_manager, fresh):
        seen.append((uuid, defn.read_text(), twin.read_text()))
        return SimpleNamespace(status="started", session_id="ses_new", tmux_session=None, detail="")

    async def get_session_info(session_id):
        return SimpleNamespace(session_row_id=row_id, tmux_session="cloude_loki", session=SimpleNamespace(tmux_created_epoch=1))

    monkeypatch.setattr(recreate_action, "recreate_by_uuid", recreate)
    app_state = SimpleNamespace(session_manager=SimpleNamespace(get_session_info=get_session_info))
    ident = asyncio.run(body._start(app_state, loki, "resume"))

    assert ident.row_id == row_id
    assert seen == [("uuid-loki", current_defn, current_twin)]
    text = defn.read_text()
    assert "pack_say" not in text and "pack_spawn" not in text and say.THREAD_LINE in text
    assert definition.WORK_RULES in text and "Odin Prime" in text
    assert definition.parse_codex_twin(twin.read_text())["name"] == "loki"
    assert note.read_text() == "a fact the agent kept\n" and (mem / "MEMORY.md").read_text() == index


def test_a_server_start_rewrites_every_live_agent_with_a_body(tmp_path, monkeypatch):
    state, repo = tmp_path / "state", tmp_path / "repo"
    state.mkdir()
    repo.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    with closing(connect(db_path_for(state), create=False)) as conn:
        for key in ("b", "g"):
            conn.execute("INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, working_dir, title, origin,"
                         " lifecycle, created_at, updated_at) VALUES (?, 'cloude', ?, 1788821572, ?, 't', 'created',"
                         " 'running', '2026-03-01T00:00:00Z', '2026-09-08T00:00:00Z')", (f"uuid-{key}", f"cloude_{key}", str(repo)))
        row_id, ghost_row = (conn.execute("SELECT id FROM sessions WHERE session_uuid = ?", (f"uuid-{k}",)).fetchone()[0] for k in "bg")
        boss = store.create_agent(conn, slug="odin", rank="project", job="repo", display_name="Odin Prime", effort="high",
                                  repo_dir=str(repo))
        store.set_session_row(conn, boss["id"], row_id)
        gone = store.create_agent(conn, slug="ghost", rank="feature", job="x", display_name="Ghost", effort="medium",
                                  repo_dir=str(tmp_path / "gone"), parent_id=boss["id"])
        store.set_session_row(conn, gone["id"], ghost_row)
        store.create_agent(conn, slug="unborn", rank="feature", job="y", display_name="Unborn", effort="medium",
                           repo_dir=str(repo), parent_id=boss["id"])
        boss = store.get_agent(conn, boss["id"])
    body_create.write_files(state, boss)
    defn = repo / ".claude" / "agents" / "odin.md"
    current = defn.read_text()
    defn.write_text(OLD)

    assert body_create.rewrite_definitions(state) == 1
    assert defn.read_text() == current and "pack_say" not in current
    assert not (repo / ".claude" / "agents" / "unborn.md").exists() and not (tmp_path / "gone").exists()
