
from __future__ import annotations

import os
from contextlib import closing
from pathlib import Path

import pytest

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import (
    SESSION_ATTRIBUTION_DERIVED_DEEPEST,
    SESSION_ATTRIBUTION_NONE,
    SESSION_ATTRIBUTION_UNKNOWN,
)
from src.core.project_writes import create_project
from src.core.session_project_binding import (
    BINDING_CREATED,
    BINDING_MATCHED,
    BINDING_MATCHED_CANONICAL,
    BINDING_NONE,
    BINDING_UNKNOWN,
    backfill_sessions_under_root,
    correct_shallow_derivations,
    columns_to_write,
    ensure_project_row,
    resolve_project_binding,
)


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    state = ensure_db_migrated(d, 4, "0.0.0")
    assert state.status == "ok", state.message
    return d


def _conn(state_dir: Path):
    return connect(db_path_for(state_dir))


def _add_project(conn, root: str, name: str) -> int:
    cur = conn.execute(
        "INSERT INTO projects (root, raw_path, display_name, source, "
        "presence, created_at, updated_at) "
        "VALUES (?, ?, ?, 'user', 'unchecked', '2026-01-01T00:00:00Z', "
        "'2026-01-01T00:00:00Z')",
        (root, root, name),
    )
    return int(cur.lastrowid)


def _add_session(conn, *, name: str, epoch: int, working_dir: str,
                 project_id=None, attribution=SESSION_ATTRIBUTION_UNKNOWN):
    cur = conn.execute(
        "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, "
        "tmux_created_epoch, origin, lifecycle, working_dir, project_id, "
        "project_attribution, created_at, updated_at) "
        "VALUES (?, 'cloude', ?, ?, 'created', 'running', ?, ?, ?, "
        "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
        (f"u-{name}-{epoch}", name, epoch, working_dir, project_id,
         attribution),
    )
    return int(cur.lastrowid)


class TestTheSymlinkSpellingRung:

    def test_short_spelling_matches_a_project_declared_at_the_long_one(
        self, state_dir: Path, tmp_path: Path
    ):
        target = tmp_path / "iCloud" / "Assistants" / "Media"
        target.mkdir(parents=True)
        link = tmp_path / "Development"
        link.symlink_to(tmp_path / "iCloud")
        with closing(_conn(state_dir)) as conn:
            with conn:
                pid = _add_project(conn, str(target), "Media")
                binding = resolve_project_binding(
                    conn, str(link / "Assistants" / "Media")
                )
        assert binding.rule == BINDING_MATCHED_CANONICAL
        assert binding.project_id == pid
        assert binding.attribution == SESSION_ATTRIBUTION_DERIVED_DEEPEST

    def test_the_as_written_match_still_wins(self, state_dir: Path,
                                             tmp_path: Path):
        target = tmp_path / "iCloud" / "App"
        target.mkdir(parents=True)
        link = tmp_path / "Development"
        link.symlink_to(tmp_path / "iCloud")
        with closing(_conn(state_dir)) as conn:
            with conn:
                at_link = _add_project(conn, str(link / "App"), "App at link")
                _add_project(conn, str(target), "App at target")
                binding = resolve_project_binding(conn, str(link / "App"))
        assert binding.rule == BINDING_MATCHED
        assert binding.project_id == at_link


class TestTheArchivedCatchAll:

    def test_an_archived_home_root_does_not_win_the_as_written_rung(
        self, state_dir: Path, tmp_path: Path
    ):
        home = tmp_path / "home"
        target = home / "iCloud" / "Media"
        target.mkdir(parents=True)
        link = home / "Development"
        link.symlink_to(home / "iCloud")
        with closing(_conn(state_dir)) as conn:
            with conn:
                catch_all = _add_project(conn, str(home), "home")
                conn.execute(
                    "UPDATE projects SET archived_at = '2026-01-02T00:00:00Z' "
                    "WHERE id = ?", (catch_all,)
                )
                media = _add_project(conn, str(target), "Media")
                binding = resolve_project_binding(
                    conn, str(link / "Media"), stored_project_id=media
                )
        assert binding.project_id == media
        assert binding.rule == BINDING_MATCHED_CANONICAL

    def test_a_live_catch_all_still_matches(self, state_dir: Path,
                                            tmp_path: Path):
        home = tmp_path / "home"
        (home / "loose").mkdir(parents=True)
        with closing(_conn(state_dir)) as conn:
            with conn:
                catch_all = _add_project(conn, str(home), "home")
                binding = resolve_project_binding(conn, str(home / "loose"))
        assert binding.project_id == catch_all
        assert binding.rule == BINDING_MATCHED


class TestThePairMovesTogether:

    def test_none_beside_a_stored_project_writes_nothing(self,
                                                         state_dir: Path):
        with closing(_conn(state_dir)) as conn:
            with conn:
                binding = resolve_project_binding(
                    conn, "/nowhere/at/all", stored_project_id=4
                )
        assert binding.rule == BINDING_NONE
        assert columns_to_write(binding, 4) == (None, None)

    def test_none_with_no_stored_project_writes_the_bare_none(
        self, state_dir: Path
    ):
        with closing(_conn(state_dir)) as conn:
            with conn:
                binding = resolve_project_binding(conn, "/nowhere/at/all")
        assert columns_to_write(binding, None) == (
            None, SESSION_ATTRIBUTION_NONE,
        )

    def test_a_match_writes_both_halves(self, state_dir: Path,
                                        tmp_path: Path):
        root = tmp_path / "repo"
        root.mkdir()
        with closing(_conn(state_dir)) as conn:
            with conn:
                pid = _add_project(conn, str(root), "repo")
                binding = resolve_project_binding(
                    conn, str(root / "sub"), stored_project_id=9
                )
        assert columns_to_write(binding, 9) == (
            pid, SESSION_ATTRIBUTION_DERIVED_DEEPEST,
        )


class TestTheNoProjectFallback:

    def test_a_directory_outside_every_root_gets_a_project_of_its_own(
        self, state_dir: Path, nonscratch_tmp_path: Path
    ):
        lonely = nonscratch_tmp_path / "lonely"
        lonely.mkdir()
        with closing(_conn(state_dir)) as conn:
            with conn:
                binding = resolve_project_binding(
                    conn, str(lonely), allow_create=True
                )
                rows = conn.execute(
                    "SELECT COUNT(*) FROM projects"
                ).fetchone()[0]
        assert binding.rule == BINDING_CREATED
        assert binding.created_project is True
        assert binding.project_id is not None
        assert binding.attribution == SESSION_ATTRIBUTION_DERIVED_DEEPEST
        assert rows == 1

    def test_minting_is_idempotent(self, state_dir: Path,
                                   nonscratch_tmp_path: Path):
        lonely = nonscratch_tmp_path / "lonely"
        lonely.mkdir()
        with closing(_conn(state_dir)) as conn:
            with conn:
                first = resolve_project_binding(
                    conn, str(lonely), allow_create=True
                )
                second = resolve_project_binding(
                    conn, str(lonely), allow_create=True
                )
                rows = conn.execute(
                    "SELECT COUNT(*) FROM projects"
                ).fetchone()[0]
        assert second.project_id == first.project_id
        assert second.created_project is False
        assert rows == 1

    def test_a_project_registered_at_the_symlink_is_not_duplicated(
        self, state_dir: Path, tmp_path: Path
    ):
        target = tmp_path / "iCloud" / "App"
        target.mkdir(parents=True)
        link = tmp_path / "Development"
        link.symlink_to(tmp_path / "iCloud")
        with closing(_conn(state_dir)) as conn:
            with conn:
                pid, created, _ = ensure_project_row(conn, str(link / "App"))
                rows = conn.execute(
                    "SELECT COUNT(*) FROM projects"
                ).fetchone()[0]
        assert created is True and rows == 1
        with closing(_conn(state_dir)) as conn:
            with conn:
                again, created_again, _ = ensure_project_row(
                    conn, str(target)
                )
                rows = conn.execute(
                    "SELECT COUNT(*) FROM projects"
                ).fetchone()[0]
        assert again == pid and created_again is False and rows == 1

    def test_a_chosen_name_names_the_minted_project(self, state_dir: Path, tmp_path: Path):
        (tmp_path / "audio").mkdir()
        (tmp_path / "other").mkdir()
        with closing(_conn(state_dir)) as conn:
            with conn:
                ensure_project_row(conn, str(tmp_path / "audio"), display_name="SoundDesk")
                ensure_project_row(conn, str(tmp_path / "other"), display_name="SoundDesk")
                names = sorted(r[0] for r in conn.execute("SELECT display_name FROM projects"))
        assert names == ["SoundDesk", "SoundDesk (2)"]

    def test_a_scratch_directory_is_the_one_exclusion(self,
                                                      state_dir: Path):
        with closing(_conn(state_dir)) as conn:
            with conn:
                binding = resolve_project_binding(
                    conn, "/private/tmp/claude-501/x", allow_create=True
                )
                rows = conn.execute(
                    "SELECT COUNT(*) FROM projects"
                ).fetchone()[0]
        assert binding.rule == BINDING_NONE
        assert rows == 0


class TestTheCreateRace:

    def test_creating_a_project_adopts_the_sessions_already_under_it(
        self, state_dir: Path, tmp_path: Path
    ):
        folder = tmp_path / "ses_5a756046"
        folder.mkdir()
        with closing(_conn(state_dir)) as conn:
            with conn:
                row_id = _add_session(
                    conn, name="cloude_Punchlist Test", epoch=1788878841,
                    working_dir=str(folder), project_id=None,
                    attribution=SESSION_ATTRIBUTION_NONE,
                )
            created = create_project(
                conn, name="Punchlist Test", path=str(folder)
            )
            after = conn.execute(
                "SELECT project_id, project_attribution FROM sessions "
                "WHERE id = ?", (row_id,)
            ).fetchone()
        assert after[0] == created["id"]
        assert after[1] == SESSION_ATTRIBUTION_DERIVED_DEEPEST

    def test_a_session_derived_onto_an_ancestor_moves_to_the_new_deeper_project(
        self, state_dir: Path, tmp_path: Path
    ):
        home = tmp_path / "home"
        folder = home / "Sparrow"
        folder.mkdir(parents=True)
        derived = SESSION_ATTRIBUTION_DERIVED_DEEPEST
        with closing(_conn(state_dir)) as conn:
            with conn:
                top = _add_project(conn, str(home), "home")
                moves = _add_session(conn, name="a", epoch=1, working_dir=str(folder),
                                     project_id=top, attribution=derived)
                stays = _add_session(conn, name="b", epoch=2, working_dir=str(folder),
                                     project_id=top, attribution="explicit")
            created = create_project(conn, name="Sparrow", path=str(folder))
            late = _add_session(conn, name="c", epoch=3, working_dir=str(folder),
                                project_id=top, attribution=derived)
            with conn:
                assert correct_shallow_derivations(conn) == 1
            got = {
                r[0]: r[1] for r in conn.execute(
                    "SELECT id, project_id FROM sessions"
                )
            }
        assert got[moves] == created["id"]
        assert got[late] == created["id"]
        assert got[stays] == top

    def test_the_backfill_never_moves_a_session_off_its_project(
        self, state_dir: Path, tmp_path: Path
    ):
        folder = tmp_path / "repo"
        (folder / "deep").mkdir(parents=True)
        with closing(_conn(state_dir)) as conn:
            with conn:
                held = _add_project(conn, str(folder / "deep"), "deep")
                row_id = _add_session(
                    conn, name="a", epoch=1, working_dir=str(folder / "deep"),
                    project_id=held,
                    attribution=SESSION_ATTRIBUTION_DERIVED_DEEPEST,
                )
                moved = backfill_sessions_under_root(
                    conn, root=str(folder), project_id=999
                )
                after = conn.execute(
                    "SELECT project_id FROM sessions WHERE id = ?", (row_id,)
                ).fetchone()[0]
        assert moved == 0
        assert after == held

    def test_the_backfill_leaves_archived_rows_alone(self, state_dir: Path,
                                                     tmp_path: Path):
        folder = tmp_path / "repo"
        folder.mkdir()
        with closing(_conn(state_dir)) as conn:
            with conn:
                row_id = _add_session(
                    conn, name="a", epoch=1, working_dir=str(folder),
                    project_id=None, attribution=SESSION_ATTRIBUTION_NONE,
                )
                conn.execute(
                    "UPDATE sessions SET archived_at = '2026-01-02T00:00:00Z' "
                    "WHERE id = ?", (row_id,)
                )
                moved = backfill_sessions_under_root(
                    conn, root=str(folder), project_id=42
                )
        assert moved == 0


class TestTheNegativeControl:

    def test_an_unreadable_directory_is_unknown_and_writes_nothing(
        self, state_dir: Path, tmp_path: Path
    ):
        root = tmp_path / "repo"
        root.mkdir()
        with closing(_conn(state_dir)) as conn:
            with conn:
                _add_project(conn, str(root), "repo")
                binding = resolve_project_binding(
                    conn, "relative/path", stored_project_id=3,
                    allow_create=True,
                )
                rows = conn.execute(
                    "SELECT COUNT(*) FROM projects"
                ).fetchone()[0]
        assert binding.rule == BINDING_UNKNOWN
        assert binding.attribution == SESSION_ATTRIBUTION_UNKNOWN
        assert binding.determined is False
        assert columns_to_write(binding, 3) == (None, None)
        assert rows == 1

    def test_a_none_probe_is_unknown_not_none(self, state_dir: Path):
        with closing(_conn(state_dir)) as conn:
            with conn:
                binding = resolve_project_binding(conn, None)
        assert binding.rule == BINDING_UNKNOWN

    def test_an_empty_projects_table_does_not_invent_a_match(
        self, state_dir: Path, tmp_path: Path
    ):
        real = tmp_path / "work"
        real.mkdir()
        with closing(_conn(state_dir)) as conn:
            with conn:
                binding = resolve_project_binding(conn, str(real))
        assert binding.rule == BINDING_NONE
        assert binding.project_id is None


class TestRestoreOnAdopt:

    def test_persist_adoption_keeps_a_stored_project_the_probe_cannot_see(
        self, state_dir: Path, tmp_path: Path
    ):
        from src.core.session_adopt_persist import persist_adoption
        from src.core.tmux_listing import TmuxListing

        target = tmp_path / "iCloud" / "Media"
        target.mkdir(parents=True)
        link = tmp_path / "Development"
        link.symlink_to(tmp_path / "iCloud")
        short = str(link / "Media")

        listing = TmuxListing.answered([{
                "name": "cloude_Media",
                "created_at_epoch": 1788444837,
                "working_dir": short,
                "tmux_session_id": "$1",
        }])
        with closing(_conn(state_dir)) as conn:
            with conn:
                pid = _add_project(conn, str(target), "Media")
                row_id = _add_session(
                    conn, name="cloude_Media", epoch=1788444837,
                    working_dir=short, project_id=pid,
                    attribution=SESSION_ATTRIBUTION_NONE,
                )
            with conn:
                result = persist_adoption(
                    conn, socket="cloude", name="cloude_Media",
                    listing=listing,
                )
            after = conn.execute(
                "SELECT project_id, project_attribution FROM sessions "
                "WHERE id = ?", (row_id,)
            ).fetchone()
        assert result.persisted, result.detail
        assert after[0] == pid
        assert after[1] == SESSION_ATTRIBUTION_DERIVED_DEEPEST

    def test_persist_adoption_never_writes_none_over_a_stored_project(
        self, state_dir: Path, tmp_path: Path
    ):
        from src.core.session_adopt_persist import persist_adoption
        from src.core.tmux_listing import TmuxListing

        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        other = tmp_path / "other"
        other.mkdir()
        listing = TmuxListing.answered([{
                "name": "cloude_X",
                "created_at_epoch": 500,
                "working_dir": str(elsewhere),
                "tmux_session_id": "$2",
        }])
        with closing(_conn(state_dir)) as conn:
            with conn:
                pid = _add_project(conn, str(other), "other")
                row_id = _add_session(
                    conn, name="cloude_X", epoch=500,
                    working_dir=str(elsewhere), project_id=pid,
                    attribution=SESSION_ATTRIBUTION_DERIVED_DEEPEST,
                )
            with conn:
                persist_adoption(
                    conn, socket="cloude", name="cloude_X", listing=listing,
                )
            after = conn.execute(
                "SELECT project_id, project_attribution FROM sessions "
                "WHERE id = ?", (row_id,)
            ).fetchone()
        assert after[0] == pid
        assert after[1] == SESSION_ATTRIBUTION_DERIVED_DEEPEST


class TestRestoreOnBootReadopt:

    def test_a_row_with_project_18_comes_back_holding_project_18(
        self, state_dir: Path, tmp_path: Path
    ):
        import inspect

        import src.core.session_boot_readopt as readopt

        source = inspect.getsource(readopt)
        assert "project_attribution" not in source
        assert "resolve_project_binding" not in source

        root = tmp_path / "CloudeCode"
        root.mkdir()
        with closing(_conn(state_dir)) as conn:
            with conn:
                pid = _add_project(conn, str(root), "CloudeCode")
                row_id = _add_session(
                    conn, name="cloude_Agent", epoch=1788813811,
                    working_dir=str(root), project_id=pid,
                    attribution=SESSION_ATTRIBUTION_DERIVED_DEEPEST,
                )
            after = conn.execute(
                "SELECT project_id, project_attribution FROM sessions "
                "WHERE id = ?", (row_id,)
            ).fetchone()
        assert after[0] == pid
        assert after[1] == SESSION_ATTRIBUTION_DERIVED_DEEPEST


class TestTheCreatePathMintsRatherThanLandingNull:

    def test_persist_creation_gives_a_new_folder_its_own_project(
        self, state_dir: Path, nonscratch_tmp_path: Path
    ):
        from src.core.session_create_persist import persist_creation
        from src.core.tmux_listing import TmuxListing

        folder = nonscratch_tmp_path / "brand_new"
        folder.mkdir()
        listing = TmuxListing.answered([{
                "name": "cloude_New",
                "created_at_epoch": 900,
                "working_dir": str(folder),
                "tmux_session_id": "$3",
        }])
        with closing(_conn(state_dir)) as conn:
            with conn:
                result = persist_creation(
                    conn, socket="cloude", name="cloude_New",
                    listing=listing, working_dir=str(folder),
                )
            row = conn.execute(
                "SELECT project_id, project_attribution FROM sessions "
                "WHERE tmux_name = ?", ("cloude_New",)
            ).fetchone()
        assert result.recorded, result.detail
        assert row[0] is not None
        assert row[1] == SESSION_ATTRIBUTION_DERIVED_DEEPEST


class TestTheSysopFallback:

    @staticmethod
    def _add_sysop(conn, project_id: int) -> None:
        conn.execute(
            "INSERT INTO swarm_agents (slug, rank, job, display_name, repo_dir, "
            "memory_scope, effort, character_seed, color_slot, thread_key, "
            "project_id, created_at, updated_at) VALUES ('alpha', 'alpha', 'j', "
            "'SysOp', '/x/alpha', 'project', 'high', 1, 1, 'all', ?, "
            "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
            (project_id,),
        )

    def test_home_folder_with_archived_project_files_under_sysop(
        self, state_dir: Path, nonscratch_tmp_path: Path
    ):
        home = nonscratch_tmp_path / "home"
        (home / "code").mkdir(parents=True)
        with closing(_conn(state_dir)) as conn:
            with conn:
                archived = _add_project(conn, str(home), "home")
                conn.execute(
                    "UPDATE projects SET archived_at = '2026-01-02T00:00:00Z' "
                    "WHERE id = ?", (archived,))
                _add_project(conn, str(home / "code"), "code")
                sysop = _add_project(conn, str(nonscratch_tmp_path / "Alpha"), "SysOp")
                self._add_sysop(conn, sysop)
                binding = resolve_project_binding(
                    conn, str(home), allow_create=True)
        assert binding.project_id == sysop
        assert binding.project_id != archived
        assert binding.rule == "fallback_sysop"
        assert binding.attribution == SESSION_ATTRIBUTION_DERIVED_DEEPEST


def test_realpath_is_what_canonical_means(tmp_path: Path):
    from src.core.transcript_import_paths import canonical

    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    assert canonical(str(link)) == os.path.realpath(str(target))


def test_a_create_refuses_the_projects_base_folder(state_dir: Path, monkeypatch):
    from fastapi import HTTPException

    from src.api import projects_service, session_crud_routes
    from src.config.settings import NEW_DEFAULT_WORKING_DIR

    monkeypatch.setattr(projects_service, "open_db_or_503", lambda _settings: _conn(state_dir))
    with pytest.raises(HTTPException) as refused:
        session_crud_routes._refuse_unsafe_project_root(None, os.path.expanduser(NEW_DEFAULT_WORKING_DIR))
    assert refused.value.status_code == 409
    session_crud_routes._refuse_unsafe_project_root(None, str(state_dir / "fine"))
