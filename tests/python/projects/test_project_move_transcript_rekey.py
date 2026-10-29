
from __future__ import annotations

from contextlib import closing

from src.core.claude_transcript_correlate import slugify_project_dir as enc
from src.core.db import connect
from src.core.project_move.apply import apply_plan
from tests.python.projects.move_world import plan_for


def _seed(conn, w):
    for folder in (w.old, w.sibling):
        name = enc(str(folder))
        path = str(w.projects / name / "t.jsonl")
        conn.execute(
            "INSERT INTO transcript_files (path, family, root, source_path, conversation_id, kind, size, mtime_ns,"
            " first_seen, last_seen, changed_at) VALUES (?, 'claude', ?, ?, ?, 'conversation', 3, 1, 'n', 'n', 'n')",
            (path, str(w.projects), f"{name}/t.jsonl", f"conv-{folder.name}"))
        conn.execute(
            "INSERT INTO session_search_live (conversation_id, path, file_kind, family, base_offset, base_line,"
            " indexed_offset, indexed_lines, rows, filter_version, in_scope, created_at, indexed_at)"
            " VALUES (?, ?, 'conversation', 'claude', 0, 0, 3, 1, 0, 'v', 1, 'n', 'n')", (f"conv-{folder.name}", path))


def test_the_moved_folders_rows_follow_it_and_a_sibling_stays(world):
    with closing(connect(world.db, create=False)) as conn:
        _seed(conn, world)
        plan = plan_for(world, move_folder=True)
        assert plan.ok, plan.failed()
        done = apply_plan(conn, plan, state_dir=world.state)
        new_name, sibling_name = enc(str(world.new)), enc(str(world.sibling))
        files = {r[0]: r[1:] for r in conn.execute("SELECT path, source_path, status, gone_at FROM transcript_files")}
        live = [r[0] for r in conn.execute("SELECT path FROM session_search_live")]
    new_path = str(world.projects / new_name / "t.jsonl")
    assert new_path in files and files[new_path] == (f"{new_name}/t.jsonl", "present", None)
    assert str(world.projects / enc(str(world.old)) / "t.jsonl") not in files
    assert str(world.projects / sibling_name / "t.jsonl") in files
    assert sorted(live) == sorted([new_path, str(world.projects / sibling_name / "t.jsonl")])
    assert done["transcript_files"] == 1 and done["search_live"] == 1


def test_a_taken_new_path_is_never_overwritten(world):
    with closing(connect(world.db, create=False)) as conn:
        _seed(conn, world)
        taken = str(world.projects / enc(str(world.new)) / "t.jsonl")
        conn.execute("INSERT INTO session_search_live (conversation_id, path, file_kind, family, base_offset, base_line,"
                     " indexed_offset, indexed_lines, rows, filter_version, in_scope, created_at, indexed_at)"
                     " VALUES ('other', ?, 'conversation', 'claude', 0, 0, 0, 0, 0, 'v', 1, 'n', 'n')", (taken,))
        from src.core.project_move.transcript_rekey import rekey_transcript_rows
        moves = [{"from": str(world.projects / enc(str(world.old))), "to": str(world.projects / enc(str(world.new)))}]
        assert rekey_transcript_rows(conn, moves)["search_live"] == 0
        assert conn.execute("SELECT COUNT(*) FROM session_search_live").fetchone()[0] == 3
