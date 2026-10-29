
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_auth_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_auth_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.project_authority import (
    MODE_DB,
    MODE_DB_UNREADABLE,
    ProjectsReadOnlyError,
    require_writable,
    resolve_projects,
)
from src.core.project_store import import_from_config
from src.core.project_writes import (
    ProjectNameAmbiguous,
    ProjectNotFound,
    ProjectRootConflict,
    create_project,
    delete_project,
    list_projects_ordered,
    resolve_by_name,
    touch_project_by_path,
    update_project,
)

REAL_CONFIG_PROJECTS: List[Dict[str, Any]] = [
    {"name": "fs2", "path": "/Users/sam/Development/scrolltest"},
    {"name": "scrolltest", "path": "/Users/sam/Development/scrolltest"},
    {"name": "test pause", "path": "/Users/sam/Development/ses_ec5bf2a3"},
    {"name": "ses_ec5bf2a3", "path": "/Users/sam/Development/ses_ec5bf2a3"},
    {"name": "asd", "path": "/Users/sam/Development/ses_8704e610"},
    {"name": "qqwe", "path": "/Users/sam/Development/ses_ec5bf2a3"},
    {"name": "Test", "path": "/Users/sam/Development/ses_c3737fbe"},
    {"name": "console-msw4z3m5", "path": "/Users/sam"},
    {"name": "claude-config-sync-2", "path": "/Users/sam/Development/claude-config-sync"},
    {"name": "claude-config-sync", "path": "/Users/sam/Development/claude-config-sync"},
    {"name": "CloudeCode", "path": "/Users/sam/Development/CloudeCode"},
    {"name": "Development", "path": "/Users/sam/Development"},
    {"name": "ai-setup", "path": "/Users/sam/Development/ai-setup"},
]

REAL_UNIQUE_ROOT_COUNT = 9


def cfg(name: str, path: str, description=None, agent_type=None) -> SimpleNamespace:
    return SimpleNamespace(
        name=name, path=path, description=description, agent_type=agent_type
    )


@pytest.fixture
def duplicate_laden_config() -> List[SimpleNamespace]:
    return [cfg(p["name"], p["path"]) for p in REAL_CONFIG_PROJECTS]


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    state = ensure_db_migrated(d, 4, "0.0.0")
    assert state.status == "ok", state.message
    return d


@pytest.fixture
def seeded(state_dir: Path, duplicate_laden_config) -> Path:
    with closing(connect(db_path_for(state_dir))) as conn:
        with conn:
            import_from_config(conn, duplicate_laden_config)
    return state_dir


def write_config(path: Path, projects: List[SimpleNamespace], **extra) -> None:
    doc: Dict[str, Any] = {"config_version": 4, "template_path": "claude-template"}
    doc.update(extra)
    doc["projects"] = [
        {"name": p.name, "path": p.path, "description": p.description}
        for p in projects
    ]
    path.write_text(json.dumps(doc, indent=2))




class TestRealDuplicateShape:

    def test_thirteen_config_entries_become_nine_rows(self, seeded: Path) -> None:
        with closing(connect(db_path_for(seeded))) as conn:
            rows = list_projects_ordered(conn)
        assert len(REAL_CONFIG_PROJECTS) == 13
        assert len(rows) == REAL_UNIQUE_ROOT_COUNT

    def test_the_triplicated_root_has_exactly_one_row(self, seeded: Path) -> None:
        with closing(connect(db_path_for(seeded))) as conn:
            rows = list_projects_ordered(conn)
        target = [
            r for r in rows if r["root"] == "/Users/sam/Development/ses_ec5bf2a3"
        ]
        assert len(target) == 1
        assert target[0]["display_name"] == "test pause"

    def test_dropped_duplicates_are_recorded_not_erased(self, seeded: Path) -> None:
        from src.core.db import get_meta
        from src.core.db_models import META_IMPORTED_FROM_JSON_RESULT

        with closing(connect(db_path_for(seeded))) as conn:
            raw = get_meta(conn, META_IMPORTED_FROM_JSON_RESULT)
        dropped = json.loads(raw)["projects_duplicate_roots_dropped"]
        names = {d["name"] for d in dropped}
        assert {"scrolltest", "ses_ec5bf2a3", "qqwe", "claude-config-sync"} <= names




class TestResolveProjectsOutcomes:

    def test_db_mode_serves_rows_and_says_it_is_authoritative(
        self, seeded: Path
    ) -> None:
        view = resolve_projects(seeded)
        assert view.mode == MODE_DB
        assert view.writable is True
        assert view.degraded is False
        assert len(view.projects) == REAL_UNIQUE_ROOT_COUNT
        assert all(p["id"] is not None for p in view.projects)

    def test_missing_db_is_named_unreadable_not_an_empty_list(
        self, tmp_path: Path
    ) -> None:
        empty_dir = tmp_path / "no_db"
        empty_dir.mkdir()
        view = resolve_projects(empty_dir)
        assert view.mode == MODE_DB_UNREADABLE
        assert view.projects == []
        assert "UNREACHABLE" in view.message
        assert "NOT a claim that you have no projects" in view.message

    def test_unreadable_refuses_writes(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "no_db2"
        empty_dir.mkdir()
        view = resolve_projects(empty_dir)
        assert view.writable is False
        with pytest.raises(ProjectsReadOnlyError):
            require_writable(view)

    def test_empty_db_is_plain_db_mode_and_not_a_warning(
        self, state_dir: Path
    ) -> None:
        view = resolve_projects(state_dir)
        assert view.mode == MODE_DB
        assert view.projects == []
        assert view.degraded is False

    def test_corrupt_db_is_unreadable_rather_than_raising(
        self, tmp_path: Path
    ) -> None:
        d = tmp_path / "corrupt"
        d.mkdir()
        db_path_for(d).write_bytes(b"this is definitely not a sqlite file" * 40)
        view = resolve_projects(d)
        assert view.mode == MODE_DB_UNREADABLE
        assert view.detail

    def test_a_failure_that_is_not_DatastoreUnreadableError_is_also_caught(
        self, seeded: Path, monkeypatch
    ) -> None:

        def boom(_conn, *, include_archived: bool = False):
            raise sqlite3.DatabaseError("database disk image is malformed")

        monkeypatch.setattr(
            "src.core.project_authority.list_projects_ordered", boom
        )
        view = resolve_projects(seeded)

        assert view.mode == MODE_DB_UNREADABLE
        assert "DatabaseError" in (view.detail or "")

    def test_resolving_never_creates_the_database(self, tmp_path: Path) -> None:
        d = tmp_path / "untouched"
        d.mkdir()
        resolve_projects(d)
        assert not db_path_for(d).exists()
