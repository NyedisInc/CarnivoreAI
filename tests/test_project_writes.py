
from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest

from src.core.db import connect, db_path_for
from src.core.project_writes import (
    ProjectNameAmbiguous,
    ProjectNameConflict,
    ProjectNotFound,
    ProjectRootConflict,
    create_project,
    delete_project,
    list_projects_ordered,
    resolve_by_name,
    touch_project_by_path,
    update_project,
)
from tests.test_project_authority import (  # noqa: F401
    REAL_UNIQUE_ROOT_COUNT,
    duplicate_laden_config,
    seeded,
    state_dir,
)




class TestWrites:

    def test_create_then_read_back(self, state_dir: Path) -> None:
        with closing(connect(db_path_for(state_dir))) as conn:
            row = create_project(conn, name="app", path="~/app", description="d")
            assert row["display_name"] == "app"
            assert row["root"] == str(Path("~/app").expanduser())
            assert row["raw_path"] == "~/app", "the user's own spelling is kept"
            assert list_projects_ordered(conn)[0]["id"] == row["id"]

    def test_name_clash_counts_local_rows_only(self, state_dir: Path) -> None:
        from src.core.hosts.remote_project import bind_remote_project
        from src.core.pack.identity.replicas import accept_replica

        with closing(connect(db_path_for(state_dir))) as conn:
            imported = bind_remote_project(conn, "peer-ab12", "/Users/a/Acme HQ", root="peer://peer-ab12/Users/a/Acme HQ")
            name = conn.execute("SELECT display_name FROM projects WHERE id = ?", (imported.project_id,)).fetchone()[0]
            answer = accept_replica(conn, home_install_id="A", project_uid="c0f1c0f1", name=name, root=str(state_dir / "replica-folder"))
            assert answer["created"] and answer["state"] == "replica"
            assert resolve_by_name(conn, name)["id"] == answer["project_id"], "the local row wins over the imported one"
            with pytest.raises(ProjectNameConflict):
                create_project(conn, name=name, path=str(state_dir / "second-folder"))

    def test_create_refuses_a_duplicate_root(self, seeded: Path) -> None:
        with closing(connect(db_path_for(seeded))) as conn:
            with pytest.raises(ProjectRootConflict):
                create_project(
                    conn,
                    name="a-fourth-name-for-it",
                    path="/Users/sam/Development/ses_ec5bf2a3",
                )

    def test_rename_changes_the_label_not_the_root(self, seeded: Path) -> None:
        with closing(connect(db_path_for(seeded))) as conn:
            target = resolve_by_name(conn, "CloudeCode")
            row = update_project(conn, target["id"], new_name="Cloude Code")
            assert row["display_name"] == "Cloude Code"
            assert row["root"] == target["root"]

    def test_rename_to_an_existing_name_is_refused(self, seeded: Path) -> None:
        from src.core.project_writes import ProjectNameConflict

        with closing(connect(db_path_for(seeded))) as conn:
            target = resolve_by_name(conn, "CloudeCode")
            with pytest.raises(ProjectNameConflict):
                update_project(conn, target["id"], new_name="Development")

    def test_empty_description_clears_and_none_leaves_alone(
        self, state_dir: Path
    ) -> None:
        with closing(connect(db_path_for(state_dir))) as conn:
            row = create_project(conn, name="p", path="/p", description="keep")
            assert update_project(conn, row["id"], new_name="p2")["description"] == "keep"
            assert update_project(conn, row["id"], description="")["description"] == ""

    def test_delete_removes_the_row_and_returns_it(self, seeded: Path) -> None:
        with closing(connect(db_path_for(seeded))) as conn:
            target = resolve_by_name(conn, "ai-setup")
            removed = delete_project(conn, target["id"])
            assert removed["root"] == target["root"]
            assert len(list_projects_ordered(conn)) == REAL_UNIQUE_ROOT_COUNT - 1
            with pytest.raises(ProjectNotFound):
                resolve_by_name(conn, "ai-setup")

    def test_delete_succeeds_when_a_stopped_session_row_still_names_the_project(
        self, state_dir: Path
    ) -> None:
        with closing(connect(db_path_for(state_dir))) as conn:
            row = create_project(conn, name="had-a-session", path="/had-a-session")
            conn.execute(
                "INSERT INTO sessions (session_uuid, project_id, working_dir, tmux_socket, tmux_name, origin, "
                "agent_type, agent_family, lifecycle, created_at, updated_at, host_key) "
                "VALUES ('u-1', ?, '/had-a-session', 'cloude', 't', 'created', 'claude', 'claude', 'stopped', 't', 't', 'local')",
                (row["id"],),
            )
            conn.commit()
            delete_project(conn, row["id"])
            kept = conn.execute("SELECT project_id FROM sessions WHERE session_uuid = 'u-1'").fetchone()
            assert kept is not None and kept[0] is None

    def test_an_ambiguous_name_is_its_own_error_not_a_guess(
        self, state_dir: Path
    ) -> None:
        with closing(connect(db_path_for(state_dir))) as conn:
            create_project(conn, name="same", path="/one")
            conn.execute(
                "INSERT INTO projects (root, raw_path, display_name, source, "
                "created_at, updated_at) VALUES ('/two','/two','same','user','t','t')"
            )
            conn.commit()
            with pytest.raises(ProjectNameAmbiguous):
                resolve_by_name(conn, "same")

    def test_touch_does_NOT_move_a_project_to_the_top(self, seeded: Path) -> None:
        with closing(connect(db_path_for(seeded))) as conn:
            before = [r["display_name"] for r in list_projects_ordered(conn)]
            assert before[0] != "ai-setup"
            touched = touch_project_by_path(
                conn, "/Users/sam/Development/ai-setup"
            )
            assert touched is not None
            assert touched["last_opened_at"] is not None, (
                "the column is kept and still written - only the ordering changed"
            )
            assert [r["display_name"] for r in list_projects_ordered(conn)] == before

    def test_touch_on_an_unknown_directory_is_a_miss_not_an_error(
        self, seeded: Path
    ) -> None:
        with closing(connect(db_path_for(seeded))) as conn:
            assert touch_project_by_path(conn, "/tmp/not-a-project") is None

    def test_import_order_is_preserved_before_anything_is_opened(
        self, seeded: Path
    ) -> None:
        with closing(connect(db_path_for(seeded))) as conn:
            names = [r["display_name"] for r in list_projects_ordered(conn)]
        assert names[0] == "fs2"
        assert names[-1] == "ai-setup"

    def test_a_newly_created_project_sorts_LAST_until_it_is_worked_in(
        self, seeded: Path
    ) -> None:
        with closing(connect(db_path_for(seeded))) as conn:
            create_project(conn, name="brand-new", path="/brand/new")
            rows = list_projects_ordered(conn)
            assert rows[-1]["display_name"] == "brand-new"
            assert rows[-1]["work_at"] is None

    def test_a_presence_refresh_does_not_reorder_the_launcher(
        self, seeded: Path
    ) -> None:
        from src.core.project_store import refresh_and_list_presence

        with closing(connect(db_path_for(seeded))) as conn:
            before = [r["display_name"] for r in list_projects_ordered(conn)]

            touch_project_by_path(conn, "/Users/sam/Development/ai-setup")
            refresh_and_list_presence(conn)

            after = [r["display_name"] for r in list_projects_ordered(conn)]

        assert after == before


def test_create_refuses_the_same_folder_through_another_spelling(state_dir: Path, tmp_path: Path) -> None:
    real = tmp_path / "real-folder"
    real.mkdir()
    link = tmp_path / "short-link"
    link.symlink_to(real)
    with closing(connect(db_path_for(state_dir))) as conn:
        first = create_project(conn, name="via-link", path=str(link))
        with pytest.raises(ProjectRootConflict) as refused:
            create_project(conn, name="via-real", path=str(real))
        assert refused.value.existing_id == first["id"]
