
from __future__ import annotations

from contextlib import closing
from pathlib import Path

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.project_writes import create_project, delete_project


def test_a_deleted_top_id_is_not_reused_by_the_next_project(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    roots = [tmp_path / name for name in ("one", "two", "three")]
    for root in roots:
        root.mkdir()
    with closing(connect(db_path_for(state))) as conn:
        first = create_project(conn, name="one", path=str(roots[0]))["id"]
        second = create_project(conn, name="two", path=str(roots[1]))["id"]
        delete_project(conn, second)
        third = create_project(conn, name="three", path=str(roots[2]))["id"]
    assert second > first
    assert third != second, f"project id {second} was reused after its project was deleted"
    assert third > second
