from __future__ import annotations

import os
import sys
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_swpp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_swpp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.project_authority import MODE_DB_UNREADABLE, resolve_projects
from src.core.project_writes import create_project
from src.core.upload_sweeper import datastore_project_paths


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    state = ensure_db_migrated(d, 4, "0.0.0")
    assert state.status == "ok", state.message
    return d


def test_readable_db_view_returns_real_project_paths(state_dir: Path) -> None:
    with closing(connect(db_path_for(state_dir))) as conn:
        with conn:
            create_project(conn, name="aa-one", path="/tmp/aa-one")
            create_project(conn, name="bb-two", path="/tmp/bb-two")

    view = resolve_projects(state_dir)
    assert view.writable is True

    paths = datastore_project_paths(view)

    assert paths is not None, (
        "a writable view with real rows must not be reported as "
        "unreadable - this is the exact regression the read_only typo caused"
    )
    assert sorted(paths) == ["/tmp/aa-one", "/tmp/bb-two"]


def test_empty_but_readable_db_returns_empty_list_not_none(state_dir: Path) -> None:
    view = resolve_projects(state_dir)
    assert view.writable is True
    assert datastore_project_paths(view) == []


def test_unreadable_db_view_returns_none(tmp_path: Path) -> None:
    missing = tmp_path / "no_db"
    missing.mkdir()

    view = resolve_projects(missing)
    assert view.mode == MODE_DB_UNREADABLE
    assert view.writable is False

    assert datastore_project_paths(view) is None
