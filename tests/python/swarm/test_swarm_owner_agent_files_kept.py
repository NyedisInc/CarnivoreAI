
from __future__ import annotations

from contextlib import closing

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.swarm import create  # noqa: F401
from src.core.swarm import body_create, teardown

USER_MD = "---\nname: builder\ndescription: my own builder\n---\n\nHand written.\n"
USER_TOML = 'name = "builder"\ndescription = "mine"\ndeveloper_instructions = "mine"\n'


def test_owner_file_is_kept_through_create_rewrite_and_teardown(tmp_path):
    state, repo = tmp_path / "state", tmp_path / "repo"
    state.mkdir()
    for sub, name, text in ((".claude/agents", "builder.md", USER_MD), (".codex/agents", "builder.toml", USER_TOML)):
        (repo / sub).mkdir(parents=True)
        (repo / sub / name).write_text(text)
    assert ensure_db_migrated(state).status == "ok"
    with closing(connect(db_path_for(state), create=False)) as conn:
        row = create._insert(conn, {"job": "builder", "rank": "task", "effort": "medium"}, str(repo))
        assert row["slug"] == "builder-2"
        clash = dict(row, slug="builder")
    body_create.write_definition(clash)
    teardown.erase_files(state, clash)
    assert (repo / ".claude/agents/builder.md").read_text() == USER_MD
    assert (repo / ".codex/agents/builder.toml").read_text() == USER_TOML
    body_create.ensure_repo(str(repo))
    body_create.write_files(state, row)
    assert (repo / ".claude/agents/builder-2.md").is_file()
    teardown.erase_files(state, row)
    assert not (repo / ".claude/agents/builder-2.md").exists() and not (repo / ".codex/agents/builder-2.toml").exists()
