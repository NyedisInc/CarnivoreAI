
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_memedit_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_memedit_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.swarm import fact_index, memory, memory_edit, store

FACT_ID = "f_0123456789ab"
ORIGINAL = '---\nid: f_0123456789ab\ntitle: "restart after swapping models"\nscope: project\norigin: handwritten\n' \
           'taught_at: "2026-10-01T00:00:00Z"\n---\n\nswap models with the model command, then restart\n'


@pytest.fixture()
def env(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    conn = connect(db_path_for(state))
    agent = store.create_agent(conn, slug="loki", rank="task", job="fix", display_name="Loki", effort="high",
                               repo_dir=str(tmp_path / "repo"))
    mem = memory.memory_dir(Path(agent["repo_dir"]), agent["slug"], agent["memory_scope"])
    memory.ensure_layout(mem)
    (mem / "facts" / f"{FACT_ID}.md").write_text(ORIGINAL, encoding="utf-8")
    fact_index.refresh_agent(conn, agent)
    yield conn, state, agent, mem
    conn.close()


def test_save_backs_up_first_and_undo_restores(env):
    conn, state, agent, mem = env
    path = f"facts/{FACT_ID}.md"
    assert [f["path"] for f in memory_edit.list_files(conn, agent["id"])] == ["MEMORY.md", path]

    edited = ORIGINAL.replace("restart after swapping models", "always restart").replace("then restart", "then restart, always")
    saved = memory_edit.save_file(conn, state, agent["id"], path, edited)
    assert "then restart, always" in (mem / path).read_text(encoding="utf-8")
    assert len(saved["backups"]) == 1
    backup = state / "swarm" / "memory-backups" / str(agent["id"]) / FACT_ID / f"{saved['backups'][0]['id']}.md"
    assert backup.read_text(encoding="utf-8") == ORIGINAL
    row = conn.execute("SELECT title, state FROM swarm_facts WHERE id = ?", (FACT_ID,)).fetchone()
    assert (row["title"], row["state"]) == ("always restart", "live")
    assert "always restart" in (mem / "MEMORY.md").read_text(encoding="utf-8")

    undone = memory_edit.restore_backup(conn, state, agent["id"], path)
    assert "then restart, always" not in undone["text"] and "then restart" in undone["text"]
    assert conn.execute("SELECT title FROM swarm_facts WHERE id = ?", (FACT_ID,)).fetchone()["title"] == \
        "restart after swapping models"
    assert len(undone["backups"]) == 2

    index = memory_edit.save_file(conn, state, agent["id"], "MEMORY.md", "# my notes\nkeep it short\n")
    assert "keep it short" in index["text"] and memory.INDEX_START in index["text"]

    with pytest.raises(memory_edit.MemoryEditRefused):
        memory_edit.save_file(conn, state, agent["id"], "../../etc/passwd", "x")
    with pytest.raises(memory_edit.MemoryEditNotFound):
        memory_edit.restore_backup(conn, state, agent["id"], path, "20990101T000000000000Z")
